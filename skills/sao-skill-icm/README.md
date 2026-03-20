# sao-skill-icm

> SAO 技能 — 查询 Microsoft ICM（Incident Management）系统的 incidents。

## 认证方式

通过 Playwright 复用 Edge 浏览器的 SSO 登录态获取 Bearer token：

```
POST https://portal.microsofticm.com/sso2/token
Content-Type: application/x-www-form-urlencoded
Cookie: (浏览器自动携带 CloudESAuthCookie)

Body: grant_type=cookie

→ Response: { "access_token": "eyJ...", "token_type": "Bearer", ... }
```

> **首次使用前**：需要在 Edge 中手动登录一次 `https://portal.microsofticm.com`。
> 之后 Playwright persistent context 会自动复用登录态。

## API

ICM OData REST API：

```
GET https://prod.microsofticm.com/api2/incidentapi/incidents?$filter=...&$select=...
Authorization: Bearer {access_token}
```

### 响应格式

```json
{
  "value": [
    {
      "Id": 123456789,
      "CreatedDate": "2026-03-19T08:30:00Z",
      "Severity": 3,
      "State": "Active",
      "Title": "Content processing pipeline timeout",
      "OwningTenantName": "News Partner Hub",
      "OwningTeamName": "Content Processing DRI",
      "OwningTeamId": 131477,
      "ContactAlias": "someone",
      "HitCount": 1,
      "ChildCount": 0,
      "ParentId": null,
      "IsCustomerImpacting": false,
      "IsNoise": false,
      "IsOutage": false,
      "ImpactStartTime": "2026-03-19T08:00:00Z",
      "CustomerName": null,
      "MitigateData": null,
      "AcknowledgeBy": "2026-03-19T09:30:00Z",
      "ExternalLinksCount": 0,
      "OwningServiceId": 12345,
      "ServiceCategoryId": null,
      "Postmortem": null,
      "RootCause": {
        "Title": null,
        "Category": null,
        "Description": null
      },
      "CustomFields": [
        { "Name": "FieldName", "Value": "FieldValue" }
      ],
      "AlertSource": {
        "AlertId": null,
        "MonitorId": null,
        "Source": "Manual"
      },
      "Bridges": []
    }
  ]
}
```

### 常用字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| Id | int | Incident ID |
| CreatedDate | datetime | 创建时间 (UTC) |
| Severity | int | 严重级别 (1-4, 1 最高) |
| State | string | 状态: Active / Mitigated / Resolved |
| Title | string | 标题 |
| OwningTeamId | int | 所属团队 ID |
| OwningTeamName | string | 所属团队名 |
| ContactAlias | string | 联系人别名 |
| HitCount | int | 命中次数 |
| ChildCount | int | 子 incident 数 |
| IsCustomerImpacting | bool | 是否影响客户 |
| IsNoise | bool | 是否噪音 |
| IsOutage | bool | 是否故障 |
| ImpactStartTime | datetime | 影响开始时间 |
| AcknowledgeBy | datetime | 需确认时间 |

## Tools

| Tool | 说明 |
|------|------|
| `query` | 查询指定 queue 的 incidents（支持按日期/状态过滤） |
| `get_incident` | 查询单个 incident 详情 |
| `summary` | incidents 统计摘要（按 severity/状态分组） |

## 配置

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `SAO_BROWSER_CHANNEL` | Playwright 使用的浏览器 | `msedge` |
| `SAO_ICM_TEAM_ID` | 默认查询的 OwningTeamId | — |
