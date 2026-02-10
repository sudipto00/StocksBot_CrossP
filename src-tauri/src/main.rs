// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::Child;
use std::sync::Mutex;

// State to manage the sidecar process
struct SidecarState {
    process: Mutex<Option<Child>>,
}

// TODO: Add custom commands for frontend-backend communication
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! Welcome to StocksBot", name)
}

// Command to show a system notification
#[tauri::command]
fn show_notification(_app: tauri::AppHandle, title: String, body: String, severity: Option<String>) -> Result<(), String> {
    // TODO: Implement cross-platform notification with severity-based styling
    // For now, just print to console
    let severity_str = severity.unwrap_or_else(|| "info".to_string());
    println!("[NOTIFICATION] {}: {} - {}", severity_str.to_uppercase(), title, body);
    
    // Future implementation:
    // app.notification()
    //     .builder()
    //     .title(&title)
    //     .body(&body)
    //     .show()
    //     .map_err(|e| e.to_string())?;
    
    Ok(())
}

// Command to get notification permission status
#[tauri::command]
fn get_notification_permission() -> Result<String, String> {
    // TODO: Check actual OS notification permissions
    // For now, return placeholder
    Ok("granted".to_string())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
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
            get_notification_permission
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}