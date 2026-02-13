// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::Child;
use std::sync::Mutex;
use serde::{Deserialize, Serialize};
use tauri_plugin_notification::{NotificationExt, PermissionState};

// State to manage the sidecar process
struct SidecarState {
    process: Mutex<Option<Child>>,
}

const KEYCHAIN_SERVICE: &str = "com.stocksbot.alpaca";

#[derive(Debug, Serialize, Deserialize)]
struct CredentialStatus {
    paper_available: bool,
    live_available: bool,
}

#[derive(Debug, Serialize, Deserialize)]
struct AlpacaCredentials {
    api_key: String,
    secret_key: String,
}

// TODO: Add custom commands for frontend-backend communication
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! Welcome to StocksBot", name)
}

// Command to show a system notification
#[tauri::command]
fn show_notification(app: tauri::AppHandle, title: String, body: String, severity: Option<String>) -> Result<(), String> {
    let trimmed_title = title.trim();
    let trimmed_body = body.trim();
    if trimmed_title.is_empty() {
        return Err("title is required".to_string());
    }
    if trimmed_body.is_empty() {
        return Err("body is required".to_string());
    }
    if trimmed_title.len() > 120 {
        return Err("title is too long".to_string());
    }
    if trimmed_body.len() > 1000 {
        return Err("body is too long".to_string());
    }

    let severity_str = severity
        .unwrap_or_else(|| "info".to_string())
        .trim()
        .to_lowercase();
    if severity_str != "info" && severity_str != "warning" && severity_str != "error" && severity_str != "success" {
        return Err("severity must be one of: info, warning, error, success".to_string());
    }
    let tagged_title = match severity_str.as_str() {
        "error" => format!("[ERROR] {}", trimmed_title),
        "warning" => format!("[WARNING] {}", trimmed_title),
        "success" => format!("[SUCCESS] {}", trimmed_title),
        _ => trimmed_title.to_string(),
    };

    app.notification()
        .builder()
        .title(&tagged_title)
        .body(trimmed_body)
        .show()
        .map_err(|e| e.to_string())?;

    Ok(())
}

// Command to get notification permission status
#[tauri::command]
fn get_notification_permission(app: tauri::AppHandle) -> Result<String, String> {
    let value = match app.notification().permission_state() {
        Ok(PermissionState::Granted) => "granted",
        Ok(PermissionState::Denied) => "denied",
        Ok(PermissionState::Prompt) => "default",
        Ok(_) => "default",
        Err(_) => "default",
    };
    Ok(value.to_string())
}

#[tauri::command]
fn request_notification_permission(app: tauri::AppHandle) -> Result<String, String> {
    let value = match app.notification().request_permission() {
        Ok(PermissionState::Granted) => "granted",
        Ok(PermissionState::Denied) => "denied",
        Ok(PermissionState::Prompt) => "default",
        Ok(_) => "default",
        Err(e) => return Err(e.to_string()),
    };
    Ok(value.to_string())
}

fn credential_username(mode: &str, field: &str) -> String {
    format!("{}_{}", mode, field)
}

fn validate_key_material(value: &str, field: &str) -> Result<String, String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Err(format!("{} is required", field));
    }
    if trimmed.len() < 8 {
        return Err(format!("{} appears too short", field));
    }
    if trimmed.len() > 512 {
        return Err(format!("{} is too long", field));
    }
    if trimmed.chars().any(|c| c.is_whitespace()) {
        return Err(format!("{} cannot contain whitespace", field));
    }
    Ok(trimmed.to_string())
}

#[tauri::command]
fn save_alpaca_credentials(mode: String, api_key: String, secret_key: String) -> Result<(), String> {
    let normalized_mode = mode.trim().to_lowercase();
    if normalized_mode != "paper" && normalized_mode != "live" {
        return Err("mode must be paper or live".to_string());
    }
    let sanitized_api_key = validate_key_material(&api_key, "api_key")?;
    let sanitized_secret_key = validate_key_material(&secret_key, "secret_key")?;

    let api_entry = keyring::Entry::new(KEYCHAIN_SERVICE, &credential_username(&normalized_mode, "api_key"))
        .map_err(|e| e.to_string())?;
    let secret_entry = keyring::Entry::new(KEYCHAIN_SERVICE, &credential_username(&normalized_mode, "secret_key"))
        .map_err(|e| e.to_string())?;

    api_entry.set_password(&sanitized_api_key).map_err(|e| e.to_string())?;
    secret_entry.set_password(&sanitized_secret_key).map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn get_alpaca_credentials(mode: String) -> Result<Option<AlpacaCredentials>, String> {
    let normalized_mode = mode.trim().to_lowercase();
    if normalized_mode != "paper" && normalized_mode != "live" {
        return Err("mode must be paper or live".to_string());
    }

    let api_entry = keyring::Entry::new(KEYCHAIN_SERVICE, &credential_username(&normalized_mode, "api_key"))
        .map_err(|e| e.to_string())?;
    let secret_entry = keyring::Entry::new(KEYCHAIN_SERVICE, &credential_username(&normalized_mode, "secret_key"))
        .map_err(|e| e.to_string())?;

    let api_key = match api_entry.get_password() {
        Ok(value) => value,
        Err(_) => return Ok(None),
    };
    let secret_key = match secret_entry.get_password() {
        Ok(value) => value,
        Err(_) => return Ok(None),
    };

    Ok(Some(AlpacaCredentials { api_key, secret_key }))
}

#[tauri::command]
fn get_alpaca_credentials_status() -> Result<CredentialStatus, String> {
    let paper_api = keyring::Entry::new(KEYCHAIN_SERVICE, &credential_username("paper", "api_key"))
        .map_err(|e| e.to_string())?;
    let paper_secret = keyring::Entry::new(KEYCHAIN_SERVICE, &credential_username("paper", "secret_key"))
        .map_err(|e| e.to_string())?;
    let live_api = keyring::Entry::new(KEYCHAIN_SERVICE, &credential_username("live", "api_key"))
        .map_err(|e| e.to_string())?;
    let live_secret = keyring::Entry::new(KEYCHAIN_SERVICE, &credential_username("live", "secret_key"))
        .map_err(|e| e.to_string())?;

    let paper_available = paper_api.get_password().is_ok() && paper_secret.get_password().is_ok();
    let live_available = live_api.get_password().is_ok() && live_secret.get_password().is_ok();

    Ok(CredentialStatus {
        paper_available,
        live_available,
    })
}

#[tauri::command]
fn clear_alpaca_credentials(mode: String) -> Result<(), String> {
    let normalized_mode = mode.trim().to_lowercase();
    if normalized_mode != "paper" && normalized_mode != "live" {
        return Err("mode must be paper or live".to_string());
    }

    let api_entry = keyring::Entry::new(KEYCHAIN_SERVICE, &credential_username(&normalized_mode, "api_key"))
        .map_err(|e| e.to_string())?;
    let secret_entry = keyring::Entry::new(KEYCHAIN_SERVICE, &credential_username(&normalized_mode, "secret_key"))
        .map_err(|e| e.to_string())?;

    let _ = api_entry.delete_password();
    let _ = secret_entry.delete_password();
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|_app| {
            // TODO: Launch Python FastAPI sidecar on app startup
            // The sidecar executable should be bundled with the app
            // Example of how to start sidecar (to be implemented):
            /*
            #[cfg(target_os = "windows")]
            let sidecar_path = app
                .path_resolver()
                .resolve_resource("backend/app.exe")
                .expect("failed to resolve sidecar");

            #[cfg(not(target_os = "windows"))]
            let sidecar_path = app
                .path_resolver()
                .resolve_resource("backend/app")
                .expect("failed to resolve sidecar");

            let child = Command::new(sidecar_path)
                .spawn()
                .expect("failed to spawn sidecar");

            app.manage(SidecarState {
                process: Mutex::new(Some(child)),
            });
            */

            println!("StocksBot is starting...");
            println!("Note: Run the Python backend separately for now using: cd backend && python app.py");
            
            Ok(())
        })
        .on_window_event(|window, event| match event {
            tauri::WindowEvent::CloseRequested { api, .. } => {
                // Hide to tray instead of closing (tray handling to be re-added for v2)
                window.hide().unwrap();
                api.prevent_close();
            }
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![
            greet,
            show_notification,
            get_notification_permission,
            request_notification_permission,
            save_alpaca_credentials,
            get_alpaca_credentials,
            get_alpaca_credentials_status,
            clear_alpaca_credentials
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
