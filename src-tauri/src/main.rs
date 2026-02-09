// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Command, Child};
use std::sync::Mutex;
use tauri::{
    CustomMenuItem, Manager, SystemTray, SystemTrayEvent, SystemTrayMenu, SystemTrayMenuItem,
};

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
fn show_notification(app: tauri::AppHandle, title: String, body: String) -> Result<(), String> {
    // TODO: Implement cross-platform notification
    // For now, just print to console
    println!("[NOTIFICATION] {}: {}", title, body);
    
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
    // Build system tray menu
    let quit = CustomMenuItem::new("quit".to_string(), "Quit StocksBot");
    let show = CustomMenuItem::new("show".to_string(), "Show Window");
    let hide = CustomMenuItem::new("hide".to_string(), "Hide Window");
    let status = CustomMenuItem::new("status".to_string(), "Backend Status").disabled();
    
    let tray_menu = SystemTrayMenu::new()
        .add_item(show)
        .add_item(hide)
        .add_native_item(SystemTrayMenuItem::Separator)
        .add_item(status)
        .add_native_item(SystemTrayMenuItem::Separator)
        .add_item(quit);
    
    let tray = SystemTray::new().with_menu(tray_menu);

    tauri::Builder::default()
        .setup(|app| {
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
        .system_tray(tray)
        .on_system_tray_event(|app, event| match event {
            SystemTrayEvent::LeftClick { .. } => {
                // Show window on tray click
                let window = app.get_window("main").unwrap();
                window.show().unwrap();
                window.set_focus().unwrap();
            }
            SystemTrayEvent::MenuItemClick { id, .. } => {
                match id.as_str() {
                    "quit" => {
                        // TODO: Cleanup sidecar process before exit
                        println!("Quitting StocksBot...");
                        std::process::exit(0);
                    }
                    "show" => {
                        let window = app.get_window("main").unwrap();
                        window.show().unwrap();
                        window.set_focus().unwrap();
                    }
                    "hide" => {
                        let window = app.get_window("main").unwrap();
                        window.hide().unwrap();
                    }
                    _ => {}
                }
            }
            _ => {}
        })
        .on_window_event(|event| match event.event() {
            tauri::WindowEvent::CloseRequested { api, .. } => {
                // Hide to tray instead of closing
                event.window().hide().unwrap();
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
