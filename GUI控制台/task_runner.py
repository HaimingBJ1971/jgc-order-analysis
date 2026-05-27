import os
import sys
from PySide6.QtCore import QObject, Signal, QProcess

# Global lock for DB writing to prevent concurrent corruption
_active_db_locks = set()

class TaskRunner(QObject):
    log_received = Signal(str)
    task_started = Signal()
    task_finished = Signal(int, str)  # exit_code, message
    
    def __init__(self, task_spec):
        super().__init__()
        self.spec = task_spec
        self.process = None
        self.db_path = task_spec.get("inputs", {}).get("db_path")
        if self.db_path:
            self.db_path = os.path.abspath(self.db_path)

    def is_locked(self):
        if self.db_path and self.db_path in _active_db_locks:
            return True
        return False

    def acquire_lock(self):
        if self.db_path:
            _active_db_locks.add(self.db_path)

    def release_lock(self):
        if self.db_path and self.db_path in _active_db_locks:
            _active_db_locks.remove(self.db_path)

    def build_command_args(self):
        """
        Builds the equivalent list of CLI args based on TaskSpec parameters
        """
        feature = self.spec.get("feature")
        inputs = self.spec.get("inputs", {})
        params = self.spec.get("params", {})
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        python_exe = os.path.abspath(os.path.join(current_dir, "..", ".venv", "bin", "python3"))
        if not os.path.exists(python_exe):
            # Fallback to system python if venv python doesn't exist
            python_exe = "python3"
            
        cmd = [python_exe]
        
        # 1. 订单+桌访合并
        if feature == "order_zhuofang":
            pos_files = inputs.get("pos_files", [])
            zhuofang_csv = inputs.get("zhuofang_csv")
            
            # If CSV is provided, run merge_order_zhuofang.py; otherwise run pure run_analysis.py
            if zhuofang_csv:
                script = os.path.abspath(os.path.join(current_dir, "..", "订单桌访合并", "merge_order_zhuofang.py"))
                cmd.append(script)
                cmd.extend(["--excel", pos_files[0], "--csv", zhuofang_csv])
                if params.get("store"):
                    cmd.extend(["--store", params.get("store")])
                if params.get("output_dir"):
                    cmd.extend(["--output-dir", params.get("output_dir")])
            else:
                script = os.path.abspath(os.path.join(current_dir, "..", "每日订单分析", "jin-gu-cang-order-analysis", "scripts", "run_analysis.py"))
                cmd.append(script)
                cmd.extend(["--excel", pos_files[0]])
                # Note: run_analysis.py writes to excel dir, or we can configure output
                
        # 2. 长期订单分析
        elif feature == "long_term":
            script = os.path.abspath(os.path.join(current_dir, "..", "长期订单分析", "main.py"))
            cmd.append(script)
            cmd.append("--files")
            cmd.extend(inputs.get("pos_files", []))
            cmd.extend(["--db", inputs.get("db_path")])
            if params.get("output_dir"):
                cmd.extend(["--output-dir", params.get("output_dir")])
                
        # 3. 周期对比分析
        elif feature == "period_compare":
            script = os.path.abspath(os.path.join(current_dir, "..", "周期对比分析", "main.py"))
            cmd.append(script)
            cmd.extend(["--excel", inputs.get("pos_files", [])[0]])
            cmd.extend(["--db", inputs.get("db_path")])
            cmd.extend(["--mode", params.get("mode", "week")])
            if params.get("store"):
                cmd.extend(["--store", params.get("store")])
            if params.get("output_dir"):
                cmd.extend(["--output-dir", params.get("output_dir")])
                
        # 4. 平台外卖统计
        elif feature == "takeaway":
            script = os.path.abspath(os.path.join(current_dir, "..", "平台外卖统计", "main.py"))
            cmd.append(script)
            cmd.append("--files")
            cmd.extend(inputs.get("takeaway_files", []))
            if inputs.get("db_path"):
                cmd.extend(["--db", inputs.get("db_path")])
            if params.get("store"):
                cmd.extend(["--store", params.get("store")])
            if params.get("output_dir"):
                cmd.extend(["--output-dir", params.get("output_dir")])
                
        return cmd

    def run(self):
        """
        Starts the QProcess asynchronously in the background.
        """
        if self.is_locked():
            self.task_finished.emit(-1, f"运行失败: 数据库 {os.path.basename(self.db_path)} 正在被另一个分析任务写入。")
            return
            
        self.acquire_lock()
        cmd_args = self.build_command_args()
        
        # Log equivalent CLI command
        self.log_received.emit(f"=== 启动任务 ({self.spec.get('feature')}) ===")
        self.log_received.emit(f"等价 CLI 命令:\n{' '.join(cmd_args)}\n")
        
        self.process = QProcess()
        # Set working directory to project root or script directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.process.setWorkingDirectory(os.path.abspath(os.path.join(current_dir, "..")))
        
        self.process.readyReadStandardOutput.connect(self._handle_stdout)
        self.process.readyReadStandardError.connect(self._handle_stderr)
        self.process.finished.connect(self._handle_finished)
        
        program = cmd_args[0]
        arguments = cmd_args[1:]
        
        self.process.start(program, arguments)
        self.task_started.emit()

    def cancel(self):
        if self.process and self.process.state() == QProcess.Running:
            self.process.terminate()
            self.log_received.emit("\n[!] 任务被用户中止。\n")
            self.release_lock()

    def _handle_stdout(self):
        data = self.process.readAllStandardOutput()
        text = bytes(data).decode('utf-8', errors='ignore')
        self.log_received.emit(text)

    def _handle_stderr(self):
        data = self.process.readAllStandardError()
        text = bytes(data).decode('utf-8', errors='ignore')
        self.log_received.emit(text)

    def _handle_finished(self, exit_code, exit_status):
        self.release_lock()
        if exit_code == 0:
            msg = "任务成功完成 ✓"
        else:
            msg = f"任务运行失败 (退出代码: {exit_code}) 🔴"
        self.task_finished.emit(exit_code, msg)
