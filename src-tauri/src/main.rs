// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Command, Child};
use std::sync::Mutex;
use tauri::{Manager, SystemTray, SystemTrayEvent};

// State to manage the sidecar process
struct SidecarState {
    process: Mutex<Option<Child>>,
}

// TODO: Add custom commands for frontend-backend communication
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! Welcome to StocksBot", name)
}

fn main() {
    // TODO: Configure system tray with proper icons and menu
    let tray = SystemTray::new();

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
                // TODO: Implement tray click behavior
                println!("System tray clicked");
            }
            SystemTrayEvent::MenuItemClick { id, .. } => {
                // TODO: Handle menu item clicks
                println!("Menu item {} clicked", id);
            }
            _ => {}
        })
        .on_window_event(|event| match event.event() {
            tauri::WindowEvent::CloseRequested { .. } => {
                // TODO: Cleanup sidecar process on exit
                println!("Window closing...");
            }
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![greet])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
