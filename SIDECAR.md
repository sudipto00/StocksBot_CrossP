# Sidecar Configuration and Cross-Platform Execution

## Overview

The StocksBot application uses a **sidecar pattern** where the Python FastAPI backend runs as a separate process managed by the Tauri main process. This document explains how to configure and bundle the sidecar for cross-platform deployment.

## Development vs Production

### Development Mode
In development, the Python backend runs as a standard Python process:
```bash
# Terminal 1: Run backend
cd backend
python app.py

# Terminal 2: Run Tauri
npm run tauri:dev
```

### Production Mode
In production, the Python backend is bundled as a standalone executable and launched automatically by Tauri.

## Creating a Standalone Python Executable

### Using PyInstaller

1. Install PyInstaller:
```bash
pip install pyinstaller
```

2. Create the executable:
```bash
cd backend
pyinstaller --onefile --name stocksbot-backend app.py
```

3. The executable will be in `backend/dist/stocksbot-backend` (or `.exe` on Windows)

### Platform-Specific Notes

#### Windows
- Output: `backend/dist/stocksbot-backend.exe`
- Bundle this in Tauri's external binaries

#### macOS
- Output: `backend/dist/stocksbot-backend`
- Ensure executable permissions: `chmod +x backend/dist/stocksbot-backend`
- May need to sign the binary for distribution

#### Linux
- Output: `backend/dist/stocksbot-backend`
- Ensure executable permissions: `chmod +x backend/dist/stocksbot-backend`

## Tauri Configuration

### 1. Update `tauri.conf.json`

Add the sidecar to external binaries:

```json
{
  "tauri": {
    "bundle": {
      "externalBin": [
        "binaries/stocksbot-backend-x86_64-pc-windows-msvc.exe",
        "binaries/stocksbot-backend-x86_64-apple-darwin",
        "binaries/stocksbot-backend-aarch64-apple-darwin",
        "binaries/stocksbot-backend-x86_64-unknown-linux-gnu"
      ],
      "resources": []
    }
  }
}
```

### 2. Organize Binary Files

Create a `binaries/` directory in the project root:

```
StocksBot_CrossP/
├── binaries/
│   ├── stocksbot-backend-x86_64-pc-windows-msvc.exe
│   ├── stocksbot-backend-x86_64-apple-darwin
│   ├── stocksbot-backend-aarch64-apple-darwin
│   └── stocksbot-backend-x86_64-unknown-linux-gnu
```

## Rust Sidecar Launch Code

Update `src-tauri/src/main.rs` to launch the sidecar:

```rust
use tauri::{api::process::{Command, CommandEvent}, Manager};

#[tauri::command]
async fn start_backend() -> Result<(), String> {
    let (mut rx, _child) = Command::new_sidecar("stocksbot-backend")
        .expect("failed to create sidecar command")
        .spawn()
        .expect("Failed to spawn sidecar");

    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => println!("Backend: {}", line),
                CommandEvent::Stderr(line) => eprintln!("Backend Error: {}", line),
                CommandEvent::Error(err) => eprintln!("Backend Error: {}", err),
                CommandEvent::Terminated(payload) => {
                    println!("Backend terminated with code: {:?}", payload.code);
                }
                _ => {}
            }
        }
    });

    Ok(())
}
```

## Environment Variables and Configuration

The sidecar can access environment variables and configuration:

1. **Port Configuration**: Ensure backend port is configurable
   ```python
   # backend/app.py
   import os
   PORT = int(os.getenv("BACKEND_PORT", "8000"))
   ```

2. **Pass from Tauri**:
   ```rust
   Command::new_sidecar("stocksbot-backend")
       .env("BACKEND_PORT", "8000")
       .spawn()
   ```

## Health Checks

Implement a health check to ensure backend is ready:

```rust
async fn wait_for_backend() -> Result<(), String> {
    let client = reqwest::Client::new();
    let mut retries = 0;
    
    while retries < 30 {
        match client.get("http://127.0.0.1:8000/status").send().await {
            Ok(_) => return Ok(()),
            Err(_) => {
                tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;
                retries += 1;
            }
        }
    }
    
    Err("Backend failed to start".to_string())
}
```

## Cleanup on Exit

Ensure the sidecar is terminated when the app closes:

```rust
.on_window_event(|event| {
    if let tauri::WindowEvent::CloseRequested { .. } = event.event() {
        // Terminate backend process
        let app_handle = event.window().app_handle();
        if let Some(backend) = app_handle.try_state::<BackendProcess>() {
            backend.kill();
        }
    }
})
```

## Testing Sidecar Integration

1. Build the Python executable
2. Place it in the correct `binaries/` location
3. Build the Tauri app: `npm run tauri:build`
4. Test the built application

## Troubleshooting

### Backend doesn't start
- Check logs in the Tauri app console
- Ensure the binary has execute permissions (Unix)
- Verify the binary path in `tauri.conf.json`

### Backend starts but connection fails
- Check if the port is already in use
- Verify CORS settings in FastAPI
- Check firewall settings

### Platform-specific issues
- Windows: May need to allow through Windows Defender
- macOS: May need to sign the binary or allow in Security settings
- Linux: Ensure all dependencies are included in the PyInstaller bundle

## Future Enhancements

- [ ] Implement graceful shutdown
- [ ] Add automatic restart on crash
- [ ] Implement IPC for better communication
- [ ] Add logging and monitoring
- [ ] Bundle Python dependencies more efficiently
- [ ] Add auto-update for sidecar
