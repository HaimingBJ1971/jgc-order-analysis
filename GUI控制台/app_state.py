import os
import json

class AppState:
    def __init__(self):
        self.config_path = os.path.expanduser("~/.jgc_gui_config.json")
        self.state = {
            "recent_dir": "",
            "default_output_dir": "",
            "default_db_path": "",
            "recent_store": "万荷店",
            "recent_period_mode": "week"
        }
        self.load()

    def load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    for k, v in saved.items():
                        if k in self.state:
                            self.state[k] = v
            except Exception as e:
                print(f"[Warning] Failed to load GUI config: {e}")

    def save(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[Warning] Failed to save GUI config: {e}")

    def get(self, key, default=None):
        return self.state.get(key, default)

    def set(self, key, value):
        if key in self.state:
            self.state[key] = value
            self.save()
