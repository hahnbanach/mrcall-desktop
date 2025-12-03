# Zylch Vue Dashboard

Modern Vue 3 web dashboard for Zylch AI - your business communication assistant.

## Quick Start

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

The app will be available at **http://localhost:5173**

## Configuration

### Backend Connection

The frontend connects to the Zylch backend at `http://localhost:8000` by default.

To change this, edit `.env`:

```bash
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

### Authentication

Authentication is handled entirely by the backend. When you click "Sign in with Google" or "Sign in with Microsoft", the frontend redirects to the backend's OAuth flow, which handles Firebase authentication server-side and returns a token.

**No Firebase configuration is needed in the frontend.**

## Available Scripts

```bash
npm run dev          # Start development server
npm run build        # Build for production
npm run preview      # Preview production build
npm run test         # Run tests
npm run lint         # Lint code
npm run type-check   # TypeScript type checking
```

## Tech Stack

- **Vue 3.5** with Composition API
- **TypeScript 5.6**
- **Vite 6** for fast builds
- **Pinia** for state management
- **Vue Router** for navigation
- **Tailwind CSS** for styling
- **Axios** for API calls

## Project Structure

```
frontend/
├── src/
│   ├── components/     # Vue components
│   │   └── layout/     # AppLayout, AppSidebar
│   ├── views/          # Page components (Dashboard, Chat, Email, etc.)
│   ├── stores/         # Pinia stores (auth, email, calendar, tasks, etc.)
│   ├── services/api/   # API service layer
│   ├── router/         # Vue Router configuration
│   ├── types/          # TypeScript type definitions
│   └── assets/         # CSS and static assets
├── public/
│   └── logo/           # Zylch logo assets
├── .env                # Environment variables
└── package.json
```

## Features

- **Dashboard** - Overview of tasks, calendar, and relationship gaps
- **Chat** - AI assistant for natural language commands
- **Email** - Thread-based email management (Gmail/Outlook)
- **Tasks** - Person-centric task tracking
- **Calendar** - Event management with Google Calendar sync
- **Contacts** - Contact intelligence and enrichment
- **Memory** - View and manage behavioral memory rules
- **Sync** - Data synchronization status and controls
- **Settings** - App configuration
- **Triggers** - Automation rules
- **Gaps** - Relationship gap analysis

## Development

### Prerequisites

- Node.js 18+
- npm 9+
- Zylch backend running on port 8000

### Running with Backend

1. Start the Zylch backend:
   ```bash
   cd ..  # Go to zylch root
   python -m zylch.api.main
   ```

2. Start the frontend:
   ```bash
   cd frontend
   npm run dev
   ```

3. Open http://localhost:5173 in your browser

## Deployment

### Vercel (Recommended)

```bash
npm i -g vercel
vercel --prod
```

Set environment variables in Vercel dashboard:
- `VITE_API_URL` - Your production backend URL

### Manual Build

```bash
npm run build
# Output in dist/ folder
```

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for detailed system design.
