# Database schema

```mermaid
erDiagram
 USERS ||--o{ CHECKINS : submits
 USERS ||--o{ ALERTS : receives
 CHECKINS ||--o| ALERTS : triggers
 USERS ||--o{ NOTES : receives
 USERS { int id PK; text name; text email UK; text role; text phone; text created_at }
 CHECKINS { int id PK; int user_id FK; int mood; int anxiety; int stress; int sleep; int safety; int social; int wellbeing; text journal; text risk; real probability; text created_at }
 ALERTS { int id PK; int user_id FK; int checkin_id FK; text status; text created_at }
 NOTES { int id PK; int user_id FK; text author; text body; text created_at }
```
