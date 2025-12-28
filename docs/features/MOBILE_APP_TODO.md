# Mobile Application - Future Development

## Status
🟡 **MEDIUM PRIORITY** - Mobile-First User Acquisition

## Business Impact

**Mobile Market Size**:
- **5.3 billion smartphone users** worldwide (2025)
- **90% of internet time** spent on mobile apps
- **Mobile-first users**: Younger professionals prefer mobile over desktop

**Why Important**:
- **User acquisition**: Reach mobile-first professionals
- **Push notifications**: Real-time relationship gap alerts
- **On-the-go access**: Check gaps while commuting, traveling
- **App Store presence**: Discoverability via iOS App Store and Google Play

**Use Cases**:
- Sales reps checking relationship gaps while traveling
- Executives quickly reviewing important contacts
- Professionals drafting quick emails on mobile
- Push notifications for urgent relationship gaps

## Current State

### What Exists
- ✅ **REST API**: All features accessible via mobile HTTP clients
- ✅ **JWT authentication**: Token-based auth works for mobile
- ✅ **Responsive web app**: Dashboard works on mobile browsers
- ✅ **Firebase Auth**: Supports mobile SDKs (iOS, Android)

### What's Missing
- ❌ **Native mobile app**: No iOS/Android applications
- ❌ **Push notifications**: No real-time mobile alerts
- ❌ **Mobile-optimized UI**: Web app not ideal for mobile
- ❌ **Offline mode**: No mobile offline support
- ❌ **Biometric auth**: No Face ID / Touch ID integration

## Planned Features

### 1. React Native Mobile App

**Why React Native**:
- **Cross-platform**: One codebase for iOS + Android
- **Fast development**: Reuse JavaScript/TypeScript skills
- **Native performance**: Near-native UI performance
- **Large ecosystem**: Many libraries and tools

**Alternative**: Flutter (if team prefers Dart)

**Tech Stack**:
```json
{
  "dependencies": {
    "react-native": "^0.73.0",
    "expo": "~50.0.0",              // Managed React Native
    "@react-navigation/native": "^6.1.9",
    "@react-navigation/bottom-tabs": "^6.5.11",
    "react-native-paper": "^5.11.0",  // Material Design UI
    "axios": "^1.6.0",               // API client
    "@react-native-firebase/app": "^19.0.0",
    "@react-native-firebase/auth": "^19.0.0",
    "@react-native-firebase/messaging": "^19.0.0",  // Push notifications
    "react-native-biometrics": "^3.0.1",  // Face ID / Touch ID
    "react-native-mmkv": "^2.11.0",  // Fast local storage
    "@react-native-async-storage/async-storage": "^1.21.0"
  }
}
```

### 2. Mobile UI/UX

**Bottom Tab Navigation**:
```typescript
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'

const Tab = createBottomTabNavigator()

function MobileApp() {
  return (
    <Tab.Navigator>
      <Tab.Screen
        name="Gaps"
        component={GapsScreen}
        options={{ tabBarIcon: 'alert-circle' }}
      />
      <Tab.Screen
        name="Tasks"
        component={TasksScreen}
        options={{ tabBarIcon: 'checkbox-marked' }}
      />
      <Tab.Screen
        name="Contacts"
        component={ContactsScreen}
        options={{ tabBarIcon: 'account-group' }}
      />
      <Tab.Screen
        name="Chat"
        component={ChatScreen}
        options={{ tabBarIcon: 'message' }}
      />
      <Tab.Screen
        name="Settings"
        component={SettingsScreen}
        options={{ tabBarIcon: 'cog' }}
      />
    </Tab.Navigator>
  )
}
```

**Key Screens**:
1. **Gaps Screen**: Swipeable cards for relationship gaps
2. **Tasks Screen**: Person-centric task list
3. **Contacts Screen**: Searchable contact list with intelligence
4. **Chat Screen**: Conversational AI interface
5. **Settings Screen**: Account, notifications, sync preferences

**Mobile-Specific Features**:
- **Swipe gestures**: Swipe to dismiss gaps, swipe to create tasks
- **Pull-to-refresh**: Refresh gaps and tasks
- **Infinite scroll**: Load more contacts as you scroll
- **Quick actions**: Long-press for context menus

### 3. Push Notifications

**Firebase Cloud Messaging (FCM)**:
```typescript
import messaging from '@react-native-firebase/messaging'

// Request permission
async function requestUserPermission() {
  const authStatus = await messaging().requestPermission()
  const enabled =
    authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
    authStatus === messaging.AuthorizationStatus.PROVISIONAL

  if (enabled) {
    console.log('Push notification permission granted')
    const fcmToken = await messaging().getToken()
    await sendTokenToServer(fcmToken)
  }
}

// Handle foreground notifications
messaging().onMessage(async remoteMessage => {
  console.log('Notification received:', remoteMessage)

  // Show local notification
  await notifee.displayNotification({
    title: remoteMessage.notification.title,
    body: remoteMessage.notification.body,
    android: {
      channelId: 'relationship-gaps',
      smallIcon: 'ic_notification',
      pressAction: { id: 'default' }
    },
    ios: {
      sound: 'default'
    }
  })
})

// Handle background/quit state notifications
messaging().setBackgroundMessageHandler(async remoteMessage => {
  console.log('Background message:', remoteMessage)
})
```

**Notification Types**:
```typescript
enum NotificationType {
  NEW_RELATIONSHIP_GAP = 'new_relationship_gap',
  URGENT_EMAIL = 'urgent_email',
  MEETING_REMINDER = 'meeting_reminder',
  TASK_DUE = 'task_due',
  CONTACT_SILENT = 'contact_silent'
}

// Example notification payload
{
  "notification": {
    "title": "Relationship Gap Alert",
    "body": "John Smith's email awaiting response (3 days)"
  },
  "data": {
    "type": "new_relationship_gap",
    "gap_id": "gap_123",
    "contact_email": "john@company.com",
    "priority": "high"
  }
}
```

**Backend Webhook**:
```python
import firebase_admin
from firebase_admin import messaging

async def send_gap_notification(user_id: str, gap: dict):
    """Send push notification for new relationship gap"""

    # Get user's FCM token from database
    user_tokens = await supabase.table('user_devices').select('fcm_token').eq(
        'user_id', user_id
    ).execute()

    for token_row in user_tokens.data:
        message = messaging.Message(
            notification=messaging.Notification(
                title='Relationship Gap Alert',
                body=f"{gap['contact_name']}'s email awaiting response ({gap['days_waiting']} days)"
            ),
            data={
                'type': 'new_relationship_gap',
                'gap_id': gap['id'],
                'contact_email': gap['contact_email'],
                'priority': str(gap['priority'])
            },
            token=token_row['fcm_token']
        )

        try:
            response = messaging.send(message)
            print(f'Push notification sent: {response}')
        except Exception as e:
            print(f'Failed to send notification: {e}')
```

### 4. Biometric Authentication

**Face ID / Touch ID**:
```typescript
import ReactNativeBiometrics from 'react-native-biometrics'

const rnBiometrics = new ReactNativeBiometrics()

// Check if biometrics available
const { available, biometryType } = await rnBiometrics.isSensorAvailable()

if (available && biometryType === BiometryTypes.FaceID) {
  console.log('FaceID is supported')
}

// Prompt for biometric authentication
const { success } = await rnBiometrics.simplePrompt({
  promptMessage: 'Confirm your identity'
})

if (success) {
  // User authenticated, proceed to app
  navigateToApp()
}
```

**Secure Token Storage**:
```typescript
import { MMKV } from 'react-native-mmkv'

const storage = new MMKV({
  id: 'zylch-secure',
  encryptionKey: 'user-biometric-key'  // Encrypted with biometric
})

// Store JWT token securely
storage.set('auth_token', jwtToken)

// Retrieve token
const token = storage.getString('auth_token')
```

### 5. Offline Support

**Local Data Cache**:
```typescript
import AsyncStorage from '@react-native-async-storage/async-storage'

// Cache relationship gaps locally
async function cacheGaps(gaps: Gap[]) {
  await AsyncStorage.setItem('cached_gaps', JSON.stringify(gaps))
}

// Load from cache when offline
async function loadGaps(): Promise<Gap[]> {
  const isOnline = await NetInfo.fetch().then(state => state.isConnected)

  if (isOnline) {
    // Fetch from API
    const gaps = await api.get('/api/gaps')
    await cacheGaps(gaps)
    return gaps
  } else {
    // Load from cache
    const cached = await AsyncStorage.getItem('cached_gaps')
    return cached ? JSON.parse(cached) : []
  }
}
```

**Offline Indicator**:
```tsx
import NetInfo from '@react-native-community/netinfo'

function OfflineBanner() {
  const [isOnline, setIsOnline] = useState(true)

  useEffect(() => {
    const unsubscribe = NetInfo.addEventListener(state => {
      setIsOnline(state.isConnected)
    })
    return () => unsubscribe()
  }, [])

  if (isOnline) return null

  return (
    <Banner visible={!isOnline} actions={[]}>
      ⚠️ You're offline. Showing cached data.
    </Banner>
  )
}
```

### 6. Deep Linking

**Handle URLs**:
```typescript
// Open app from notification or email link
// zylch://gap/gap_123
// zylch://contact/john@company.com

import { Linking } from 'react-native'

Linking.addEventListener('url', ({ url }) => {
  if (url.startsWith('zylch://gap/')) {
    const gapId = url.replace('zylch://gap/', '')
    navigation.navigate('GapDetail', { gapId })
  } else if (url.startsWith('zylch://contact/')) {
    const email = url.replace('zylch://contact/', '')
    navigation.navigate('ContactDetail', { email })
  }
})
```

## Technical Requirements

### Development Environment
```bash
# Install React Native CLI
npm install -g react-native-cli

# Install Expo CLI (recommended)
npm install -g expo-cli

# iOS development (macOS only)
brew install cocoapods
xcode-select --install

# Android development
# Install Android Studio with SDK
```

### Platform-Specific
**iOS**:
- Xcode 15+ (macOS required)
- iOS 14+ target
- Apple Developer Account ($99/year)

**Android**:
- Android Studio
- Android SDK 24+ (Android 7.0+)
- Google Play Developer Account ($25 one-time)

### CI/CD
```yaml
# .github/workflows/mobile-build.yml
name: Build Mobile App

on:
  push:
    branches: [main, mobile-dev]

jobs:
  build-ios:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build iOS app
        run: |
          cd mobile
          npx expo build:ios --non-interactive

  build-android:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build Android APK
        run: |
          cd mobile
          npx expo build:android --non-interactive
```

## Implementation Phases

### Phase 1: Expo Setup (Week 1)
**Duration**: 3-4 days
**Tasks**:
1. Initialize Expo project with React Native
2. Set up navigation (React Navigation)
3. Configure Firebase (Auth, Messaging)
4. Create basic screens (Gaps, Tasks, Contacts)
5. Test on iOS and Android simulators

### Phase 2: Core Features (Week 2-3)
**Duration**: 7-10 days
**Tasks**:
1. Implement Gaps screen with swipeable cards
2. Implement Tasks screen with person-centric view
3. Implement Contacts screen with search
4. Implement Chat screen with conversational AI
5. Integrate with backend REST API
6. Add pull-to-refresh and offline caching

### Phase 3: Push Notifications (Week 3)
**Duration**: 3-4 days
**Tasks**:
1. Set up FCM for iOS and Android
2. Request notification permissions
3. Handle foreground/background notifications
4. Implement deep linking from notifications
5. Test notification delivery

### Phase 4: Biometric Auth (Week 4)
**Duration**: 2-3 days
**Tasks**:
1. Integrate React Native Biometrics
2. Implement Face ID / Touch ID login
3. Secure token storage
4. Test on real devices

### Phase 5: Polish & Beta (Week 4-5)
**Duration**: 5-7 days
**Tasks**:
1. Design mobile-specific UI/UX
2. Add animations and gestures
3. Optimize performance
4. Beta test with TestFlight (iOS) and internal testing (Android)
5. Fix bugs from beta feedback

### Phase 6: App Store Release (Week 6)
**Duration**: 3-5 days
**Tasks**:
1. Create App Store and Play Store listings
2. Prepare screenshots and videos
3. Submit for review (iOS: 1-3 days, Android: 1-2 days)
4. Launch publicly

## Success Metrics

### Technical Metrics
- **App Size**: <50MB download (iOS and Android)
- **Launch Time**: <3 seconds cold start
- **Battery Usage**: <5% battery drain per hour of active use
- **Crash Rate**: <1% of sessions

### Business Metrics
- **Mobile Downloads**: 10,000+ in first 3 months
- **Mobile DAU**: >40% of mobile users active daily
- **Mobile-Only Users**: >25% of users are mobile-only
- **App Store Rating**: >4.5 stars (both iOS and Android)

### User Experience Metrics
- **Onboarding Completion**: >80% complete mobile onboarding
- **Push Notification CTR**: >30% click-through rate
- **Daily Engagement**: Average 3+ sessions per day

## Related Documentation

- **API**: `docs/api/` - REST API endpoints for mobile clients
- **Frontend**: `frontend/ARCHITECTURE.md` - Design patterns to reuse
- **Push Notifications**: Backend webhook implementation

## Open Questions

1. **Expo vs Bare React Native**: Use Expo or eject to bare RN?
   - **Proposal**: Start with Expo, eject if needed for advanced features

2. **iOS vs Android Priority**: Which platform to launch first?
   - **Proposal**: Launch both simultaneously (React Native supports both)

3. **Tablet Support**: Should we optimize for iPad and Android tablets?
   - **Proposal**: v1 = phone only, v2 = tablet-optimized layouts

4. **Wearables**: Apple Watch or Android Wear support?
   - **Proposal**: Future phase (v3), focus on phone first

5. **Offline Capabilities**: What works offline vs requires internet?
   - **Proposal**: Read-only offline (view gaps, tasks, contacts), write requires online

---

**Priority**: 🟡 **MEDIUM - Mobile-First User Acquisition**

**Owner**: Mobile Team (New hire or contractor)

**Dependencies**:
- REST API (already exists)
- Firebase project setup
- Apple Developer Account
- Google Play Developer Account

**Next Steps**:
1. Research React Native vs Flutter
2. Set up Expo development environment
3. Create proof-of-concept mobile app
4. Beta test with internal team

**Estimated Timeline**: 6-8 weeks

**Last Updated**: December 2025
