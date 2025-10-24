SELECT * FROM alpha_events


SELECT * from alpha_notifications

SELECT * from alpha_notification_logs


ALTER TABLE alpha_events DROP INDEX uk_event_token_time;
ALTER TABLE alpha_events ADD UNIQUE INDEX uk_event_token_raw_time (token, raw_time);
