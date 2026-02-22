// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use serde::{Deserialize, Serialize};
use tauri::menu::{MenuBuilder, MenuItem, MenuItemBuilder, PredefinedMenuItem};
use tauri::image::Image;
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_notification::{NotificationExt, PermissionState};

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

#[derive(Debug, Clone, Deserialize)]
struct TraySummaryPayload {
    runner_status: Option<String>,
    broker_connected: Option<bool>,
    poll_errors: Option<u64>,
    open_positions: Option<u64>,
    active_strategy: Option<String>,
    universe: Option<String>,
    optimizer_active_jobs: Option<u64>,
    optimizer_queue_depth: Option<u64>,
    optimizer_stalled_jobs: Option<u64>,
    last_update: Option<String>,
    // Financial summary
    equity: Option<f64>,
    cash: Option<f64>,
    daily_pnl: Option<f64>,
    daily_pnl_pct: Option<f64>,
}

struct TrayState {
    runner_item: Mutex<Option<MenuItem<tauri::Wry>>>,
    broker_item: Mutex<Option<MenuItem<tauri::Wry>>>,
    account_item: Mutex<Option<MenuItem<tauri::Wry>>>,
    summary_item: Mutex<Option<MenuItem<tauri::Wry>>>,
    toggle_runner_item: Mutex<Option<MenuItem<tauri::Wry>>>,
    runner_running: Mutex<bool>,
    last_snapshot: Mutex<String>,
}

struct SidecarState {
    process: Mutex<Option<Child>>,
    /// Signal the watchdog thread to stop.
    watchdog_stop: Arc<AtomicBool>,
    /// How many times the watchdog has auto-restarted the sidecar.
    restart_count: AtomicU32,
}

impl Default for SidecarState {
    fn default() -> Self {
        Self {
            process: Mutex::new(None),
            watchdog_stop: Arc::new(AtomicBool::new(false)),
            restart_count: AtomicU32::new(0),
        }
    }
}

impl Default for TrayState {
    fn default() -> Self {
        Self {
            runner_item: Mutex::new(None),
            broker_item: Mutex::new(None),
            account_item: Mutex::new(None),
            summary_item: Mutex::new(None),
            toggle_runner_item: Mutex::new(None),
            runner_running: Mutex::new(false),
            last_snapshot: Mutex::new("Status unavailable".to_string()),
        }
    }
}

const TRAY_ID: &str = "main-tray";
const MENU_ID_SHOW: &str = "show_window";
const MENU_ID_HIDE: &str = "hide_window";
const MENU_ID_TOGGLE_RUNNER: &str = "toggle_runner";
const MENU_ID_QUIT: &str = "quit_app";

fn sanitize_short(value: Option<String>, fallback: &str, max_len: usize) -> String {
    let cleaned = value.unwrap_or_else(|| fallback.to_string()).trim().to_string();
    if cleaned.is_empty() {
        return fallback.to_string();
    }
    let mut out = cleaned;
    if out.len() > max_len {
        out.truncate(max_len);
    }
    out
}

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn hide_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
}

fn update_tray_status_ui(app: &AppHandle, payload: &TraySummaryPayload) -> Result<(), String> {
    let runner = sanitize_short(payload.runner_status.clone(), "unknown", 24).to_uppercase();
    let broker = if payload.broker_connected.unwrap_or(false) {
        "Connected".to_string()
    } else {
        "Degraded".to_string()
    };
    let poll_errors = payload.poll_errors.unwrap_or(0);
    let open_positions = payload.open_positions.unwrap_or(0);
    let strategy = sanitize_short(payload.active_strategy.clone(), "None", 36);
    let universe = sanitize_short(payload.universe.clone(), "N/A", 28);
    let active_jobs = payload.optimizer_active_jobs.unwrap_or(0);
    let queue_depth = payload.optimizer_queue_depth.unwrap_or(0);
    let stalled_jobs = payload.optimizer_stalled_jobs.unwrap_or(0);
    let last_update = sanitize_short(payload.last_update.clone(), "-", 24);
    let snapshot = format!(
        "Runner: {} | Broker: {} | Poll Errors: {} | Open Positions: {} | Jobs: {} active / {} queued{} | Strategy: {} | Universe: {} | Updated: {}",
        runner,
        broker,
        poll_errors,
        open_positions,
        active_jobs,
        queue_depth,
        if stalled_jobs > 0 {
            format!(" | Stalled: {}", stalled_jobs)
        } else {
            "".to_string()
        },
        strategy,
        universe,
        last_update
    );

    if let Some(state) = app.try_state::<TrayState>() {
        let is_running = runner == "RUNNING";
        if let Ok(mut guard) = state.runner_running.lock() {
            *guard = is_running;
        }
        if let Ok(guard) = state.runner_item.lock() {
            if let Some(item) = &*guard {
                let _ = item.set_text(format!("Runner: {}", runner));
            }
        }
        if let Ok(guard) = state.broker_item.lock() {
            if let Some(item) = &*guard {
                let _ = item.set_text(format!(
                    "Broker: {} | Poll Errors: {} | Open Positions: {}",
                    broker, poll_errors, open_positions
                ));
            }
        }
        if let Ok(guard) = state.account_item.lock() {
            if let Some(item) = &*guard {
                let equity_str = match payload.equity {
                    Some(v) => format!("${:.2}", v),
                    None => "N/A".to_string(),
                };
                let cash_str = match payload.cash {
                    Some(v) => format!("${:.2}", v),
                    None => "N/A".to_string(),
                };
                let pnl_str = match (payload.daily_pnl, payload.daily_pnl_pct) {
                    (Some(pnl), Some(pct)) => {
                        let sign = if pnl >= 0.0 { "+" } else { "" };
                        format!("{}${:.2} ({}{}%)", sign, pnl.abs(), sign, format!("{:.2}", pct))
                    }
                    (Some(pnl), None) => {
                        let sign = if pnl >= 0.0 { "+" } else { "-" };
                        format!("{}${:.2}", sign, pnl.abs())
                    }
                    _ => "N/A".to_string(),
                };
                let _ = item.set_text(format!(
                    "Equity: {} | Cash: {} | Day P&L: {}",
                    equity_str, cash_str, pnl_str
                ));
            }
        }
        if let Ok(guard) = state.summary_item.lock() {
            if let Some(item) = &*guard {
                let _ = item.set_text(format!(
                    "Strategy: {} | Universe: {} | Jobs: {}/{}{}",
                    strategy,
                    universe,
                    active_jobs,
                    queue_depth,
                    if stalled_jobs > 0 {
                        format!(" | Stalled {}", stalled_jobs)
                    } else {
                        "".to_string()
                    },
                ));
            }
        }
        if let Ok(guard) = state.toggle_runner_item.lock() {
            if let Some(item) = &*guard {
                let label = if is_running { "Pause Runner" } else { "Resume Runner" };
                let _ = item.set_text(label);
            }
        }
        if let Ok(mut guard) = state.last_snapshot.lock() {
            *guard = snapshot.clone();
        }
    }

    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        let equity_tip = match payload.equity {
            Some(v) => format!("${:.0}", v),
            None => "N/A".to_string(),
        };
        let _ = tray.set_tooltip(Some(format!(
            "StocksBot | Equity {} | Runner {} | Broker {} | Positions {} | {}",
            equity_tip,
            runner,
            broker,
            open_positions,
            last_update
        )));
    }
    Ok(())
}

const BACKEND_URL: &str = "http://127.0.0.1:8000";
const BACKEND_ADDR: &str = "127.0.0.1:8000";

/// Quick TCP-level reachability check (used before HTTP is available).
fn is_backend_tcp_reachable() -> bool {
    let addr: SocketAddr = match BACKEND_ADDR.parse() {
        Ok(parsed) => parsed,
        Err(_) => return false,
    };
    TcpStream::connect_timeout(&addr, Duration::from_millis(350)).is_ok()
}

/// Full HTTP health check — confirms the backend is responding to requests.
fn is_backend_healthy() -> bool {
    let agent = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(2))
        .timeout(Duration::from_secs(5))
        .build();
    match agent.get(&format!("{}/status", BACKEND_URL)).call() {
        Ok(resp) => resp.status() == 200,
        Err(_) => false,
    }
}

/// Wait for the backend to become healthy after launch.
/// Polls up to `max_attempts` times with `interval` between each attempt.
fn wait_for_backend_ready(max_attempts: u32, interval: Duration) -> bool {
    for attempt in 1..=max_attempts {
        if is_backend_healthy() {
            println!("Backend healthy after {} attempt(s)", attempt);
            return true;
        }
        std::thread::sleep(interval);
    }
    // Final attempt — maybe it just needs one more second
    is_backend_healthy()
}

/// Background watchdog that monitors backend health and auto-restarts on failure.
/// Runs in a dedicated thread. Emits `backend-health` events to the frontend.
fn start_backend_watchdog(app_handle: AppHandle) {
    let stop_flag = {
        let state = app_handle.state::<SidecarState>();
        state.watchdog_stop.clone()
    };

    std::thread::Builder::new()
        .name("backend-watchdog".into())
        .spawn(move || {
            let mut consecutive_failures: u32 = 0;
            let max_failures_before_restart: u32 = 3;
            let max_auto_restarts_per_session: u32 = 5;

            // Give the backend time to fully boot before first check
            std::thread::sleep(Duration::from_secs(15));

            loop {
                if stop_flag.load(Ordering::Relaxed) {
                    println!("Backend watchdog stopping");
                    break;
                }

                if is_backend_healthy() {
                    if consecutive_failures > 0 {
                        println!("Backend recovered after {} failure(s)", consecutive_failures);
                        let _ = app_handle.emit("backend-health", "healthy");
                    }
                    consecutive_failures = 0;
                } else {
                    consecutive_failures += 1;
                    println!(
                        "Backend health check failed ({}/{})",
                        consecutive_failures, max_failures_before_restart
                    );

                    if consecutive_failures >= max_failures_before_restart {
                        let _ = app_handle.emit("backend-health", "unhealthy");

                        let restart_count = {
                            let state = app_handle.state::<SidecarState>();
                            state.restart_count.load(Ordering::Relaxed)
                        };

                        if restart_count < max_auto_restarts_per_session {
                            println!("Attempting backend auto-restart #{}", restart_count + 1);

                            // Kill stale process if it exists
                            if let Some(state) = app_handle.try_state::<SidecarState>() {
                                if let Ok(mut guard) = state.process.lock() {
                                    if let Some(mut child) = guard.take() {
                                        // Check if process is still alive
                                        match child.try_wait() {
                                            Ok(Some(_)) => {
                                                // Already exited
                                            }
                                            _ => {
                                                let _ = child.kill();
                                                let _ = child.wait();
                                            }
                                        }
                                    }
                                }
                            }

                            // Attempt re-launch
                            if let Some(child) = launch_backend_sidecar(&app_handle) {
                                if let Some(state) = app_handle.try_state::<SidecarState>() {
                                    if let Ok(mut guard) = state.process.lock() {
                                        *guard = Some(child);
                                    }
                                    state.restart_count.fetch_add(1, Ordering::Relaxed);
                                }

                                // Wait for the restarted backend to come up
                                if wait_for_backend_ready(60, Duration::from_millis(500)) {
                                    println!("Backend restarted successfully");
                                    let _ = app_handle.emit("backend-health", "restarted");
                                    consecutive_failures = 0;
                                } else {
                                    println!("Backend restart: process launched but not healthy yet");
                                }
                            } else {
                                println!("Backend restart failed: could not find binary or script");
                            }
                        } else {
                            println!(
                                "Backend auto-restart limit reached ({}/{}). Manual restart required.",
                                restart_count, max_auto_restarts_per_session
                            );
                        }
                    }
                }

                // Poll every 10 seconds
                for _ in 0..10 {
                    if stop_flag.load(Ordering::Relaxed) {
                        break;
                    }
                    std::thread::sleep(Duration::from_secs(1));
                }
            }
        })
        .expect("Failed to spawn backend watchdog thread");
}

fn find_backend_script(app: &AppHandle) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join("../backend/app.py"));
        candidates.push(cwd.join("backend/app.py"));
    }
    if let Ok(resource_dir) = app.path().resource_dir() {
        // Tauri bundles `../backend/app.py` as `_up_/backend/app.py`
        candidates.push(resource_dir.join("_up_/backend/app.py"));
        candidates.push(resource_dir.join("backend/app.py"));
        candidates.push(resource_dir.join("app.py"));
    }
    for candidate in candidates {
        if candidate.exists() && candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

fn find_backend_binary(app: &AppHandle) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join("../backend/dist/stocksbot-backend"));
        candidates.push(cwd.join("../backend/dist/stocksbot-backend.exe"));
        candidates.push(cwd.join("backend/dist/stocksbot-backend"));
        candidates.push(cwd.join("backend/dist/stocksbot-backend.exe"));
    }
    if let Ok(resource_dir) = app.path().resource_dir() {
        // Tauri bundles `../backend/dist/stocksbot-backend` as `_up_/backend/dist/stocksbot-backend`
        candidates.push(resource_dir.join("_up_/backend/dist/stocksbot-backend"));
        candidates.push(resource_dir.join("_up_/backend/dist/stocksbot-backend.exe"));
        candidates.push(resource_dir.join("backend/dist/stocksbot-backend"));
        candidates.push(resource_dir.join("backend/dist/stocksbot-backend.exe"));
        candidates.push(resource_dir.join("stocksbot-backend"));
        candidates.push(resource_dir.join("stocksbot-backend.exe"));
    }
    for candidate in candidates {
        if candidate.exists() && candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

fn launch_backend_sidecar(app: &AppHandle) -> Option<Child> {
    if is_backend_tcp_reachable() {
        println!("Backend already reachable at {}; skipping sidecar launch.", BACKEND_ADDR);
        return None;
    }
    if let Some(binary) = find_backend_binary(app) {
        let mut cmd = Command::new(&binary);
        if let Some(parent) = binary.parent() {
            cmd.current_dir(parent);
        }
        cmd.stdin(Stdio::null());
        cmd.stdout(Stdio::null());
        cmd.stderr(Stdio::null());
        match cmd.spawn() {
            Ok(child) => {
                println!("Launched backend sidecar binary {}", binary.display());
                return Some(child);
            }
            Err(e) => {
                println!(
                    "Failed to launch backend sidecar binary {}: {}",
                    binary.display(),
                    e
                );
            }
        }
    }
    let script = match find_backend_script(app) {
        Some(path) => path,
        None => {
            println!("Backend sidecar script not found. Run backend manually if needed.");
            return None;
        }
    };

    let mut last_error = String::new();
    for interpreter in ["python3", "python"] {
        let mut cmd = Command::new(interpreter);
        cmd.arg(&script);
        if let Some(parent) = script.parent() {
            cmd.current_dir(parent);
        }
        cmd.stdin(Stdio::null());
        cmd.stdout(Stdio::null());
        cmd.stderr(Stdio::null());
        match cmd.spawn() {
            Ok(child) => {
                println!(
                    "Launched backend sidecar using {} {}",
                    interpreter,
                    script.display()
                );
                return Some(child);
            }
            Err(e) => {
                last_error = e.to_string();
            }
        }
    }

    println!(
        "Failed to launch backend sidecar for {}: {}",
        script.display(),
        last_error
    );
    None
}

fn stop_backend_sidecar(app: &AppHandle) {
    if let Some(state) = app.try_state::<SidecarState>() {
        if let Ok(mut guard) = state.process.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
                println!("Stopped backend sidecar process");
            }
        }
    }
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

#[tauri::command]
fn update_tray_summary(app: tauri::AppHandle, payload: TraySummaryPayload) -> Result<(), String> {
    update_tray_status_ui(&app, &payload)
}

#[derive(Debug, Serialize)]
struct BackendHealthStatus {
    healthy: bool,
    restart_count: u32,
}

#[tauri::command]
fn check_backend_health(app: tauri::AppHandle) -> Result<BackendHealthStatus, String> {
    let healthy = is_backend_healthy();
    let restart_count = app
        .try_state::<SidecarState>()
        .map(|s| s.restart_count.load(Ordering::Relaxed))
        .unwrap_or(0);
    Ok(BackendHealthStatus {
        healthy,
        restart_count,
    })
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            println!("StocksBot is starting...");
            app.manage(SidecarState::default());

            let app_handle = app.handle().clone();
            if let Some(child) = launch_backend_sidecar(&app_handle) {
                let sidecar_state = app.state::<SidecarState>();
                if let Ok(mut guard) = sidecar_state.process.lock() {
                    *guard = Some(child);
                }

                // Wait for the backend to become fully healthy (up to 30s)
                // PyInstaller one-file binaries need ~16s to extract + boot
                println!("Waiting for backend to become healthy...");
                if wait_for_backend_ready(60, Duration::from_millis(500)) {
                    println!("Backend is healthy and ready");
                } else {
                    println!("Warning: backend launched but not responding to health checks yet");
                }
            } else if is_backend_healthy() {
                println!("External backend already healthy at {}", BACKEND_ADDR);
            } else {
                println!("Note: backend is not running. Start it manually: cd backend && python app.py");
            }

            // Start the background watchdog to monitor backend health
            start_backend_watchdog(app_handle.clone());

            app.manage(TrayState::default());

            let runner_item = MenuItemBuilder::new("Runner: STARTING")
                .enabled(false)
                .build(app)
                .map_err(|e| e.to_string())?;
            let broker_item = MenuItemBuilder::new("Broker: Unknown | Poll Errors: 0 | Open Positions: 0")
                .enabled(false)
                .build(app)
                .map_err(|e| e.to_string())?;
            let account_item = MenuItemBuilder::new("Equity: N/A | Cash: N/A | Day P&L: N/A")
                .enabled(false)
                .build(app)
                .map_err(|e| e.to_string())?;
            let summary_item = MenuItemBuilder::new("Strategy: None | Universe: N/A")
                .enabled(false)
                .build(app)
                .map_err(|e| e.to_string())?;
            let show_item = MenuItemBuilder::with_id(MENU_ID_SHOW, "Show StocksBot")
                .build(app)
                .map_err(|e| e.to_string())?;
            let hide_item = MenuItemBuilder::with_id(MENU_ID_HIDE, "Hide Window")
                .build(app)
                .map_err(|e| e.to_string())?;
            let toggle_runner_item = MenuItemBuilder::with_id(MENU_ID_TOGGLE_RUNNER, "Resume Runner")
                .build(app)
                .map_err(|e| e.to_string())?;
            let quit_item = MenuItemBuilder::with_id(MENU_ID_QUIT, "Quit")
                .build(app)
                .map_err(|e| e.to_string())?;
            let separator_a = PredefinedMenuItem::separator(app).map_err(|e| e.to_string())?;
            let separator_b = PredefinedMenuItem::separator(app).map_err(|e| e.to_string())?;
            let tray_menu = MenuBuilder::new(app)
                .items(&[
                    &runner_item,
                    &broker_item,
                    &account_item,
                    &summary_item,
                    &separator_a,
                    &show_item,
                    &hide_item,
                    &toggle_runner_item,
                    &separator_b,
                    &quit_item,
                ])
                .build()
                .map_err(|e| e.to_string())?;

            let tray_state = app.state::<TrayState>();
            if let Ok(mut guard) = tray_state.runner_item.lock() {
                *guard = Some(runner_item.clone());
            }
            if let Ok(mut guard) = tray_state.broker_item.lock() {
                *guard = Some(broker_item.clone());
            }
            if let Ok(mut guard) = tray_state.account_item.lock() {
                *guard = Some(account_item.clone());
            }
            if let Ok(mut guard) = tray_state.summary_item.lock() {
                *guard = Some(summary_item.clone());
            }
            if let Ok(mut guard) = tray_state.toggle_runner_item.lock() {
                *guard = Some(toggle_runner_item.clone());
            }

            let tray_icon_image = Image::from_bytes(include_bytes!("../icons/tray-icon.png"))
                .map_err(|e| e.to_string())?;

            TrayIconBuilder::with_id(TRAY_ID)
                .icon(tray_icon_image)
                .icon_as_template(false)
                .menu(&tray_menu)
                .show_menu_on_left_click(true)
                .tooltip("StocksBot running in background")
                .on_menu_event(|app, event| {
                    match event.id().as_ref() {
                        MENU_ID_SHOW => show_main_window(app),
                        MENU_ID_HIDE => hide_main_window(app),
                        MENU_ID_TOGGLE_RUNNER => {
                            let _ = app.emit("tray-toggle-runner", "toggle");
                        }
                        MENU_ID_QUIT => app.exit(0),
                        _ => {}
                    }
                })
                .build(app)
                .map_err(|e| e.to_string())?;
            
            Ok(())
        })
        .on_window_event(|window, event| match event {
            tauri::WindowEvent::CloseRequested { api, .. } => {
                let _ = window.hide();
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
            clear_alpaca_credentials,
            update_tray_summary,
            check_backend_health
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                // Signal watchdog to stop before killing the sidecar
                if let Some(state) = app.try_state::<SidecarState>() {
                    state.watchdog_stop.store(true, Ordering::Relaxed);
                }
                stop_backend_sidecar(app);
            }
        });
}
