# Notifications Guide

This guide explains how to use the notification system in StocksBot.

## Overview

StocksBot provides a cross-platform notification system that works on Windows, macOS, and Linux. Notifications can be triggered from:
- The frontend (UI events, user actions)
- The backend (trade executions, alerts, system events)
- The Tauri layer (system tray events)

## Architecture

```
┌─────────────────────────────────────────┐
│         Frontend (React)                │
│  utils/notifications.ts                 │
│  ├─ showNotification()                  │
│  └─ getNotificationPermission()         │
└───────────────┬─────────────────────────┘
                │ invoke()
                ▼
┌─────────────────────────────────────────┐
│         Tauri (Rust)                    │
│  src/main.rs                            │
│  ├─ show_notification command           │
│  └─ System notification API             │
└───────────────┬─────────────────────────┘
                │ OS API
                ▼
        ┌───────────────┐
        │  OS Notification │
        │  System          │
        └───────────────┘
```

## Frontend Usage

### Basic Notification

```typescript
import { showNotification, NotificationSeverity } from '../utils/notifications';

// Show a notification
await showNotification(
  'Trade Executed',
  'Bought 100 shares of AAPL at $150.00',
  NotificationSeverity.SUCCESS
);
```

### Convenience Functions

```typescript
import {
  showSuccessNotification,
  showErrorNotification,
  showWarningNotification,
  showInfoNotification
} from '../utils/notifications';

// Success notification
await showSuccessNotification('Order Filled', 'Your buy order has been filled');

// Error notification
await showErrorNotification('Connection Lost', 'Lost connection to backend');

// Warning notification
await showWarningNotification('Risk Limit', 'Approaching daily loss limit');

// Info notification
await showInfoNotification('Market Open', 'The market is now open');
```

### Check Permission

```typescript
import { getNotificationPermission } from '../utils/notifications';

const permission = await getNotificationPermission();
if (permission === 'granted') {
  // Show notifications
} else {
  // Request permission or show in-app notifications
}
```

## Backend Integration

The backend can request notifications via the `/notifications` endpoint:

```python
# Example: Notify user of trade execution
from api.models import NotificationRequest, NotificationSeverity

notification = NotificationRequest(
    title="Trade Executed",
    message="Bought 100 shares of AAPL at $150.00",
    severity=NotificationSeverity.SUCCESS
)

# POST to /notifications endpoint
# Frontend will receive and display via websocket (TODO)
```

## OS-Specific Setup

### Windows

Windows 10+ supports notifications natively via the Action Center.

**No additional setup required** - notifications work out of the box.

**Troubleshooting:**
- If notifications don't appear, check Windows Settings → System → Notifications & actions
- Ensure "Get notifications from apps and other senders" is enabled
- Add StocksBot to allowed apps if needed

### macOS

macOS notifications require proper app signing and entitlements.

**Setup:**
1. Notifications work in development mode
2. For production, ensure proper code signing
3. Users may need to grant permission on first launch

**Troubleshooting:**
- Check System Preferences → Notifications → StocksBot
- Ensure "Allow Notifications" is enabled
- Set "StocksBot alert style" to "Banners" or "Alerts"

**Permission Request:**
```rust
// TODO: Implement macOS-specific permission request
// Will be triggered on first notification attempt
```

### Linux

Linux notification support varies by desktop environment.

**Supported:**
- GNOME (via libnotify)
- KDE Plasma
- XFCE
- Most modern desktop environments

**Setup:**
1. Ensure `libnotify` is installed:
   ```bash
   # Ubuntu/Debian
   sudo apt-get install libnotify-bin
   
   # Fedora
   sudo dnf install libnotify
   
   # Arch
   sudo pacman -S libnotify
   ```

2. For development, you may need `libayatana-appindicator3-dev`:
   ```bash
   sudo apt-get install libayatana-appindicator3-dev
   ```

**Troubleshooting:**
- If notifications don't appear, check your desktop environment's notification settings
- Test with: `notify-send "Test" "This is a test notification"`
- Some minimal window managers may not support notifications

## Notification Levels

The system supports four severity levels:

| Severity | Use Case | Example |
|----------|----------|---------|
| `INFO` | General information | Market opened, Strategy started |
| `SUCCESS` | Positive events | Order filled, Profit target hit |
| `WARNING` | Warnings that need attention | Risk limit approaching, Connection issue |
| `ERROR` | Errors and failures | Order rejected, Backend crash |

## Current Limitations

⚠️ **TODO Items:**

1. **Persistence**: Notifications are not persisted - they disappear after being shown
2. **WebSocket**: Backend → Frontend notification push not implemented (polling needed)
3. **Rich Content**: Only text notifications supported (no images, actions)
4. **History**: No notification history/log
5. **Preferences**: No per-notification-type preferences
6. **Sound**: No sound support yet
7. **Badge**: App icon badge count not implemented

## Future Enhancements

Planned features for the notification system:

- [ ] Notification history/log in UI
- [ ] Per-severity notification preferences
- [ ] Custom sound selection
- [ ] Rich notifications (images, action buttons)
- [ ] Notification grouping
- [ ] Do Not Disturb mode
- [ ] Desktop/mobile notification sync
- [ ] WebSocket for real-time backend notifications
- [ ] Email/SMS notification fallback

## Example: Complete Integration

Here's a complete example showing frontend + backend integration:

**Frontend (React component):**
```typescript
import { showSuccessNotification } from '../utils/notifications';
import { createOrder } from '../api/backend';

async function handleBuyOrder() {
  try {
    const order = await createOrder({
      symbol: 'AAPL',
      side: OrderSide.BUY,
      type: OrderType.MARKET,
      quantity: 100
    });
    
    // Show success notification
    await showSuccessNotification(
      'Order Submitted',
      `Buy order for 100 shares of AAPL submitted`
    );
  } catch (error) {
    await showErrorNotification(
      'Order Failed',
      error.message
    );
  }
}
```

**Backend (FastAPI):**
```python
@router.post("/orders")
async def create_order(request: OrderRequest):
    # ... process order ...
    
    # Queue notification (TODO: Implement push via WebSocket)
    notification = NotificationRequest(
        title="Order Filled",
        message=f"Buy order for {request.quantity} shares of {request.symbol} filled at ${fill_price}",
        severity=NotificationSeverity.SUCCESS
    )
    
    # For now, notifications are pull-based via polling
    # Future: Push via WebSocket
```

## Testing Notifications

To test notifications in development:

```typescript
import { showNotification, NotificationSeverity } from '../utils/notifications';

// In your component or dev console
showNotification(
  'Test Notification',
  'This is a test notification',
  NotificationSeverity.INFO
);
```

---

**Last Updated:** 2024  
**Version:** 0.1.0
