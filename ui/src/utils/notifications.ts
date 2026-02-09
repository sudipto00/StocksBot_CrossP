/**
 * Notification utilities.
 * Helpers for showing system notifications via Tauri.
 */

import { invoke } from '@tauri-apps/api/tauri';

export enum NotificationSeverity {
  INFO = 'info',
  WARNING = 'warning',
  ERROR = 'error',
  SUCCESS = 'success',
}

/**
 * Show a system notification.
 * 
 * @param title - Notification title
 * @param body - Notification body text
 * @param severity - Notification severity (optional)
 * 
 * @example
 * showNotification('Trade Executed', 'Bought 100 shares of AAPL', NotificationSeverity.SUCCESS);
 */
export async function showNotification(
  title: string,
  body: string,
  severity: NotificationSeverity = NotificationSeverity.INFO
): Promise<void> {
  try {
    // Call Tauri command to show notification
    await invoke('show_notification', { title, body });
    console.log(`[Notification] ${severity}: ${title} - ${body}`);
  } catch (error) {
    console.error('Failed to show notification:', error);
  }
}

/**
 * Check if notifications are supported/permitted.
 * 
 * @returns 'granted', 'denied', or 'default'
 */
export async function getNotificationPermission(): Promise<string> {
  try {
    const permission = await invoke<string>('get_notification_permission');
    return permission;
  } catch (error) {
    console.error('Failed to check notification permission:', error);
    return 'denied';
  }
}

/**
 * Request notification permission (placeholder).
 * 
 * TODO: Implement actual permission request flow per OS
 */
export async function requestNotificationPermission(): Promise<boolean> {
  // TODO: Implement OS-specific permission request
  // For now, assume granted
  console.log('[Notifications] Permission request (not implemented)');
  return true;
}

/**
 * Show a success notification.
 */
export async function showSuccessNotification(title: string, body: string): Promise<void> {
  return showNotification(title, body, NotificationSeverity.SUCCESS);
}

/**
 * Show a warning notification.
 */
export async function showWarningNotification(title: string, body: string): Promise<void> {
  return showNotification(title, body, NotificationSeverity.WARNING);
}

/**
 * Show an error notification.
 */
export async function showErrorNotification(title: string, body: string): Promise<void> {
  return showNotification(title, body, NotificationSeverity.ERROR);
}

/**
 * Show an info notification.
 */
export async function showInfoNotification(title: string, body: string): Promise<void> {
  return showNotification(title, body, NotificationSeverity.INFO);
}
