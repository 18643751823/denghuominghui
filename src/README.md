# 键盘鼠标计数工具 - 重构说明

## 新项目结构

```
src/
├── core/               # 核心业务逻辑
│   ├── __init__.py
│   ├── models.py       # 数据模型
│   ├── services.py     # 业务服务
│   └── utils.py        # 工具函数
├── data/               # 数据存储
│   └── usage_stats.db
├── ui/                 # 用户界面
│   ├── __init__.py
│   ├── components/     # UI组件
│   ├── views/          # 视图窗口
│   └── styles/         # 样式表
├── tests/              # 单元测试
│   ├── __init__.py
│   ├── test_models.py
│   └── test_services.py
└── main.py            # 程序入口
```

## 重构目标

1. 提高代码可读性和可维护性
2. 模块化设计，职责分离
3. 添加完善的类型提示
4. 统一代码风格
5. 添加单元测试
6. 优化UI初始化流程