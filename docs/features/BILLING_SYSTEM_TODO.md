---
description: |
  [TODO - Critical Priority] Stripe billing - the revenue generation blocker. Tiers: Free (1
  account, 100 emails/month), Pro ($29/month, 3 accounts, unlimited), Team ($99/month, 10 users,
  shared intelligence). Multi-tenant architecture and all feature infrastructure already exist.
  Requires Stripe checkout, subscription management, usage tracking, and webhook handling.
---

# Billing System - Future Development

## Status
🔴 **CRITICAL PRIORITY** - Revenue Generation Blocker

## Business Impact

**Revenue Model**: Subscription-based SaaS
- **Free Tier**: Basic features (1 email account, 100 emails/month)
- **Pro Tier**: $29/month (3 accounts, unlimited emails, priority support)
- **Team Tier**: $99/month (10 users, shared intelligence, admin dashboard)

**Why Critical**:
- **Blocks monetization**: No payment system = no revenue
- **Go-to-market dependency**: Can't launch publicly without billing
- **Investor requirement**: SaaS business model requires payment infrastructure
- **Competitive advantage**: First-mover in AI relationship intelligence

**Projected Revenue** (Conservative):
- Month 1-3: 50 users → $1,450/month
- Month 4-6: 200 users → $5,800/month
- Month 7-12: 500 users → $14,500/month

## Current State

### What Exists
- ✅ **Multi-tenant architecture** (Firebase Auth + Supabase RLS)
- ✅ **User management** (registration, login, JWT validation)
- ✅ **Feature infrastructure** (email sync, gaps, tasks, memory)
- ✅ **API endpoints** (all features accessible via REST API)
- ✅ **Frontend dashboard** (Vue 3, deployed on Vercel)

### What's Missing
- ❌ **Stripe integration** (payment processing)
- ❌ **Subscription management** (plans, upgrades, cancellations)
- ❌ **Feature gating** (Free vs Pro tier enforcement)
- ❌ **Usage tracking** (API calls, email quotas)
- ❌ **Billing UI** (subscription page, payment method management)
- ❌ **Webhook handlers** (subscription events, payment failures)
- ❌ **Trial logic** (14-day free trial for Pro tier)

## Planned Features

### 1. Stripe Integration

**Payment Processing**:
- Stripe Checkout for new subscriptions
- Stripe Customer Portal for self-service management
- Secure payment method storage
- PCI compliance (handled by Stripe)

**Subscription Plans**:
```javascript
const PLANS = {
  free: {
    id: 'free',
    name: 'Free',
    price: 0,
    features: {
      emailAccounts: 1,
      emailsPerMonth: 100,
      storage: '1GB',
      support: 'community'
    }
  },
  pro: {
    id: 'price_pro_monthly',
    name: 'Pro',
    price: 29,
    currency: 'EUR',
    interval: 'month',
    features: {
      emailAccounts: 3,
      emailsPerMonth: Infinity,
      storage: '10GB',
      support: 'priority',
      advancedFeatures: true
    },
    trialDays: 14
  },
  team: {
    id: 'price_team_monthly',
    name: 'Team',
    price: 99,
    currency: 'EUR',
    interval: 'month',
    features: {
      users: 10,
      emailAccounts: 30,
      emailsPerMonth: Infinity,
      storage: '100GB',
      support: 'dedicated',
      sharedIntelligence: true,
      adminDashboard: true
    }
  }
}
```

### 2. Feature Gating

**Database Schema** (`users` table):
```sql
ALTER TABLE users ADD COLUMN subscription_tier TEXT DEFAULT 'free';
ALTER TABLE users ADD COLUMN subscription_status TEXT DEFAULT 'active';
ALTER TABLE users ADD COLUMN trial_ends_at TIMESTAMP;
ALTER TABLE users ADD COLUMN stripe_customer_id TEXT;
ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT;
```

**Feature Gate Middleware**:
```python
@app.middleware("http")
async def check_feature_access(request: Request, call_next):
    user = request.state.user
    endpoint = request.url.path

    # Check feature access based on tier
    if endpoint.startswith('/api/chat'):
        require_tier(user, ['pro', 'team'])
    elif endpoint.startswith('/api/sharing'):
        require_tier(user, ['team'])
    elif endpoint.startswith('/api/gaps'):
        # Check email quota for free tier
        if user.tier == 'free':
            check_email_quota(user, limit=100)

    return await call_next(request)
```

### 3. Usage Tracking

**Track API Calls**:
- Email syncs per month
- Chat messages sent
- Archive storage used
- Gap analyses requested

**Database Schema** (`usage_tracking` table):
```sql
CREATE TABLE usage_tracking (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES users(id),
  resource_type TEXT NOT NULL, -- 'email_sync', 'chat', 'storage', 'gap_analysis'
  usage_count INTEGER NOT NULL DEFAULT 1,
  month TEXT NOT NULL, -- 'YYYY-MM' format
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(user_id, resource_type, month)
);
```

**Usage Middleware**:
```python
async def track_usage(user_id: str, resource_type: str):
    month = datetime.now().strftime('%Y-%m')
    await supabase.rpc('increment_usage', {
        'p_user_id': user_id,
        'p_resource_type': resource_type,
        'p_month': month
    })
```

### 4. Billing UI (Frontend)

**Subscription Page** (`/settings/billing`):
- Current plan and usage
- Upgrade/downgrade options
- Payment method management
- Billing history
- Invoice downloads

**Components**:
- `PlanSelector.vue` - Choose plan with feature comparison
- `PaymentForm.vue` - Stripe Elements for card input
- `BillingHistory.vue` - Past invoices and payments
- `UsageMetrics.vue` - Current month usage vs limits

### 5. Webhook Handlers

**Stripe Events to Handle**:
```python
STRIPE_EVENTS = [
    'customer.subscription.created',  # New subscription
    'customer.subscription.updated',  # Plan change, trial end
    'customer.subscription.deleted',  # Cancellation
    'invoice.payment_succeeded',      # Successful payment
    'invoice.payment_failed',         # Failed payment
    'customer.updated',               # Payment method change
]
```

**Webhook Endpoint** (`/api/webhooks/stripe`):
```python
@app.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )

        if event.type == 'customer.subscription.created':
            await handle_subscription_created(event.data.object)
        elif event.type == 'customer.subscription.deleted':
            await handle_subscription_deleted(event.data.object)
        elif event.type == 'invoice.payment_failed':
            await handle_payment_failed(event.data.object)

        return {'status': 'success'}
    except ValueError as e:
        return {'error': 'Invalid payload'}, 400
```

### 6. Trial Logic

**14-Day Free Trial for Pro**:
- Automatic trial start on subscription
- Full Pro features during trial
- Email reminder 3 days before trial ends
- Automatic charge at trial end (unless canceled)

**Trial Management**:
```python
async def start_trial(user_id: str):
    trial_end = datetime.now() + timedelta(days=14)
    await supabase.table('users').update({
        'subscription_tier': 'pro',
        'subscription_status': 'trialing',
        'trial_ends_at': trial_end.isoformat()
    }).eq('id', user_id).execute()

    # Schedule trial ending reminder
    schedule_email(
        to=user.email,
        subject='Your Zylch AI trial ends in 3 days',
        template='trial_ending',
        send_at=trial_end - timedelta(days=3)
    )
```

## Technical Requirements

### Backend Dependencies
```bash
pip install stripe>=8.0.0
pip install python-dateutil
```

### Environment Variables
```bash
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID_PRO=price_...
STRIPE_PRICE_ID_TEAM=price_...
```

### Database Migrations
```sql
-- Add subscription columns
ALTER TABLE users ADD COLUMN subscription_tier TEXT DEFAULT 'free';
ALTER TABLE users ADD COLUMN subscription_status TEXT DEFAULT 'active';
ALTER TABLE users ADD COLUMN trial_ends_at TIMESTAMP;
ALTER TABLE users ADD COLUMN stripe_customer_id TEXT;
ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT;

-- Create usage tracking table
CREATE TABLE usage_tracking (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES users(id),
  resource_type TEXT NOT NULL,
  usage_count INTEGER NOT NULL DEFAULT 1,
  month TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(user_id, resource_type, month)
);

-- Create invoices table
CREATE TABLE invoices (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES users(id),
  stripe_invoice_id TEXT UNIQUE NOT NULL,
  amount_paid INTEGER NOT NULL, -- in cents
  currency TEXT DEFAULT 'EUR',
  status TEXT NOT NULL, -- 'paid', 'open', 'void'
  invoice_pdf TEXT, -- Stripe hosted PDF URL
  created_at TIMESTAMP DEFAULT NOW()
);
```

## Implementation Phases

### Phase 1: Stripe Setup (Week 1)
**Duration**: 5-7 days
**Tasks**:
1. Create Stripe account and get API keys
2. Create subscription products and prices in Stripe Dashboard
3. Add Stripe SDK to backend
4. Implement `/api/billing/create-checkout-session` endpoint
5. Test checkout flow in Stripe test mode
6. Set up Stripe webhook endpoint
7. Configure webhook signature verification

### Phase 2: Feature Gating (Week 2)
**Duration**: 5-7 days
**Tasks**:
1. Add subscription columns to `users` table (migration)
2. Create feature gate middleware
3. Implement tier checking logic
4. Add usage tracking (emails, chats, storage)
5. Create `GET /api/billing/usage` endpoint
6. Test Free tier limitations
7. Test Pro tier unlocking

### Phase 3: Frontend Billing UI (Week 3)
**Duration**: 5-7 days
**Tasks**:
1. Create `BillingPage.vue` component
2. Integrate Stripe Elements for payment
3. Build plan comparison table
4. Implement upgrade/downgrade flows
5. Add usage meters and limits display
6. Create billing history view
7. Test complete user flow (sign up → trial → upgrade)

### Phase 4: Webhook Handlers (Week 4)
**Duration**: 3-5 days
**Tasks**:
1. Implement `customer.subscription.created` handler
2. Implement `customer.subscription.deleted` handler
3. Implement `invoice.payment_failed` handler
4. Add retry logic for failed webhooks
5. Create admin alert system for payment failures
6. Test webhook delivery with Stripe CLI
7. Deploy webhook endpoint to production

### Phase 5: Trial & Polish (Week 5)
**Duration**: 3-5 days
**Tasks**:
1. Implement 14-day trial logic
2. Create trial reminder emails
3. Add subscription cancellation flow
4. Implement downgrade logic (end of billing period)
5. Create admin dashboard for subscription overview
6. Test edge cases (expired cards, cancellations, refunds)
7. Write billing documentation

## Success Metrics

### Technical Metrics
- **Payment Success Rate**: >95% of attempted payments succeed
- **Webhook Reliability**: >99.9% webhook delivery success
- **Feature Gate Accuracy**: 100% enforcement (no unauthorized access)
- **Page Load Time**: Billing page loads in <2 seconds

### Business Metrics
- **Trial-to-Paid Conversion**: >20% of trials convert to paid
- **Monthly Recurring Revenue (MRR)**: $10,000+ by month 6
- **Churn Rate**: <5% monthly churn
- **Customer Lifetime Value (LTV)**: >$500 per user

### User Experience Metrics
- **Checkout Completion**: >70% of users complete checkout
- **Time to Subscribe**: <3 minutes from signup to paid subscription
- **Support Tickets (Billing)**: <5% of users contact support about billing

## Related Documentation

- **Architecture**: `docs/ARCHITECTURE.md` - Multi-tenant architecture
- **API**: `docs/api/auth-api.md` - User authentication and JWT
- **Frontend**: `frontend/ARCHITECTURE.md` - Vue 3 dashboard
- **Development Plan**: `.claude/DEVELOPMENT_PLAN.md` - Phase H details

## Open Questions

1. **Tax Compliance**: Do we need to collect VAT for EU customers?
   - Consider: Stripe Tax for automatic tax calculation

2. **Refund Policy**: What's our refund policy for cancellations?
   - Proposal: Pro-rated refunds within 30 days

3. **Annual Plans**: Should we offer annual subscriptions with discount?
   - Proposal: 20% discount for annual (10 months price for 12 months)

4. **Team Billing**: Who pays for Team tier? Admin only or shared?
   - Proposal: Admin is billing contact, can add payment delegates

5. **Grandfathering**: How do we handle free beta users when launching?
   - Proposal: Free users keep current features, new features require upgrade

6. **Payment Methods**: Beyond cards, do we accept SEPA, PayPal, wire transfer?
   - Proposal: Start with cards only, add SEPA for European B2B later

---

**Priority**: 🔴 **CRITICAL - START IMMEDIATELY**

**Owner**: Backend Team (Mario)

**Dependencies**:
- Stripe account creation
- SSL certificate for webhook endpoint
- Email service for trial reminders

**Next Steps**:
1. Create Stripe account
2. Set up test environment
3. Implement Phase 1 (Stripe Setup)
4. Review and approve pricing strategy

**Last Updated**: December 2025
