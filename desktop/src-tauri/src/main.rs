#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, OpenOptions};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{Manager, WindowEvent};

struct BackendState {
    child: Mutex<Option<Child>>,
}

fn detect_project_root() -> PathBuf {
    if let Ok(v) = std::env::var("MALODY_PROJECT_DIR") {
        return PathBuf::from(v);
    }
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));

    // Walk up parent directories to find a valid project root.
    let mut cursor = Some(cwd.as_path());
    while let Some(dir) = cursor {
        if dir.join("app").join("main.py").exists() || dir.join("run.py").exists() {
            return dir.to_path_buf();
        }
        // Also accept repo layouts where package root is nested as "malody_api".
        if dir.join("malody_api").join("run.py").exists()
            || dir.join("malody_api").join("app").join("main.py").exists()
        {
            return dir.join("malody_api");
        }
        cursor = dir.parent();
    }

    // Fallback to current directory if no marker was found.
    cwd
}

fn detect_run_py(root: &Path) -> PathBuf {
    // 目录重整后的入口：app/main.py
    let p = root.join("app").join("main.py");
    if p.exists() {
        return p;
    }
    // 兼容旧布局的根目录 run.py
    let legacy = root.join("run.py");
    if legacy.exists() {
        return legacy;
    }
    root.join("app").join("main.py")
}

fn spawn_backend(root: &Path) -> Result<Child, String> {
    let python = std::env::var("MALODY_API_PYTHON").unwrap_or_else(|_| "python".to_string());
    let run_py = detect_run_py(root);
    if !run_py.exists() {
        return Err(format!("run.py not found at {}", run_py.display()));
    }

    let logs_dir = root.join("logs");
    fs::create_dir_all(&logs_dir).map_err(|e| format!("failed to create logs dir: {e}"))?;
    let log_file = logs_dir.join("gui_backend.log");
    let stdout = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_file)
        .map_err(|e| format!("failed to open backend log: {e}"))?;
    let stderr = stdout
        .try_clone()
        .map_err(|e| format!("failed to clone backend log fd: {e}"))?;

    let mut command = Command::new(python);
    command
        .arg(run_py)
        .current_dir(root)
        .env("MALODY_API_HOST", "127.0.0.1")
        .env("MALODY_API_PORT", "18765")
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));

    command.spawn().map_err(|e| format!("failed to spawn backend: {e}"))
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let root = detect_project_root();
            let child = spawn_backend(&root)?;
            app.manage(BackendState {
                child: Mutex::new(Some(child)),
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                let state = window.state::<BackendState>();
                let mut guard = match state.child.lock() {
                    Ok(g) => g,
                    Err(_) => return,
                };
                if let Some(mut child) = guard.take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
