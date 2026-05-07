"""
配置参数模块
"""

# ── 时间窗口（从会话首单下单时间算起，超过则不合并） ──
T_WINDOW_HOURS_REGULAR = 1    # 普通桌台：1小时
T_WINDOW_HOURS_PRIVATE = 3    # 包间：3小时

# ── 并发拆单识别（同桌多人各自扫码同时下单） ──
CONCURRENT_MINUTES = 5        # 两笔订单下单时间差 < 5分钟视为并发，直接合并

# ── 加单金额上限（硬约束，超过则判定为新客翻台） ──
ADD_ON_MAX_RATIO = 0.50       # 候选订单收入 > 锚点订单收入 × 50% 则不合并

# ── 结账后间隔（结账后超过此间隔且非小单，判定为翻台） ──
T_REOPEN_MIN_REGULAR = 30     # 普通桌台：30分钟
T_REOPEN_MIN_PRIVATE = 120    # 包间：120分钟

# ── 小单识别阈值 ──
SETTLE_GRACE_MIN = 15         # 紧邻结账的强合并区间（分钟）
SMALL_RATIO = 0.30            # 小单比例阈值（收入 <= 锚点 × 30%）
SMALL_LINE_CNT = 2            # 小单商品行数阈值

# ── 弱规则打分 ──
SCORE_THRESHOLD = 60          # 弱规则打分阈值（0-100）
SMALL_ORDER_BONUS_LOW = 55    # 40元以下小单加分
SMALL_ORDER_BONUS_MID = 30    # 40-60元小单加分
SMALL_ORDER_BONUS_HIGH = 15   # 60元以上小单加分

# ── 包间晚餐「纯酒水加单」强合并（避免人数登记不一致导致弱规则不达标） ──
# 订单本地时间的小时落在 [DINNER_MERGE_START_HOUR, DINNER_MERGE_END_HOUR) 视为晚餐时段
DINNER_MERGE_START_HOUR = 17
DINNER_MERGE_END_HOUR = 23
