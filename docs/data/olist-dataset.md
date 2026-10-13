# Olist匿名真实电商数据

## 数据来源

- 名称：Brazilian E-Commerce Public Dataset by Olist
- 来源：<https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce>
- 许可：CC BY-NC-SA 4.0
- 时间范围：2016—2018年
- 说明：Olist公开的匿名真实商业数据

原始CSV放在`data/raw/olist`，该目录被Git忽略，不随项目提交。

## 数据真实性边界

直接来自原数据：

- 匿名订单和客户ID
- 订单状态与购买、发货、实际送达、预计送达时间
- 商品类别、价格、运费和卖家
- 支付方式、分期数和支付金额
- 评价分数及评论

项目派生字段：

- `OL000001`形式的稳定订单别名，方便演示和口述。
- `demo_phone_last4`由匿名`customer_unique_id`经过SHA-256确定性生成，
  仅用于身份校验演示，不是真实手机号。
- 中文订单状态由原始英文状态映射得到。
- 是否延迟、延迟天数和数据快照日内的签收天数。

模拟数据：

- 商城退款和发票政策。
- 客服工单及其处理状态。
- 商品是否拆封。原数据没有该字段，程序不会伪造；七天内退款会返回“需人工审核”。

## 导入

```powershell
.\.venv\Scripts\python.exe scripts\import_olist.py
```

数据库已存在时，确认需要完整重建再使用：

```powershell
.\.venv\Scripts\python.exe scripts\import_olist.py --force
```

脚本先生成临时SQLite数据库，所有表写入并创建索引后才替换正式文件，避免失败时留下
半成品。输出数据库为`data/olist_support.db`。

## 关系表

| 表 | 作用 |
| --- | --- |
| `olist_customers` | 匿名客户、地区和演示验证后四位 |
| `olist_orders` | 订单状态、时间和物流派生特征 |
| `olist_order_items` | 订单商品明细、价格和运费 |
| `olist_products` | 商品类别和尺寸属性 |
| `olist_sellers` | 匿名卖家与地区 |
| `olist_order_payments` | 支付方式、分期和金额 |
| `olist_order_reviews` | 评分和评论 |
| `olist_support_tickets` | 项目生成的客服工单 |
| `dataset_metadata` | 来源、许可、快照日期和边界说明 |

核心连接关系：

```text
customers 1 ── N orders 1 ── N order_items N ── 1 products
                         ├── N payments
                         ├── N reviews
                         └── N support_tickets
```

## 当前导入结果

- 99,441笔订单
- 112,650条订单商品明细
- 103,886条支付记录
- 99,224条评价记录
- 32,951种商品
- 3,095名匿名卖家
- 孤儿订单明细：0
- 重复订单别名：0

机器可读报告：`data/evaluation/olist_import_report.json`

## 演示订单

| 订单 | 演示后四位 | 特征 |
| --- | --- | --- |
| `OL099422` | `3623` | 运输中、超过预计送达时间、评分1分 |
| `OL099415` | `4882` | 已签收、电脑配件、评分5分 |
| `OL080724` | `0347` | 快照日内刚签收，但缺少拆封状态，退款需人工审核 |
| `OL099441` | `6192` | 已取消 |
