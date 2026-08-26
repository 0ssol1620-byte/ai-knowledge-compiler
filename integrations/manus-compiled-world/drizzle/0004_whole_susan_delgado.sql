CREATE TABLE `agent_audit_events` (
	`id` int AUTO_INCREMENT NOT NULL,
	`project_id` int NOT NULL,
	`agent_id` int,
	`event_type` varchar(80) NOT NULL,
	`detail_json` text NOT NULL,
	`created_at` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `agent_audit_events_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `file_server_agents` (
	`id` int AUTO_INCREMENT NOT NULL,
	`project_id` int NOT NULL,
	`name` varchar(160) NOT NULL,
	`agent_status` enum('pending','active','revoked','error') NOT NULL DEFAULT 'pending',
	`scoped_roots_json` text NOT NULL,
	`enrollment_secret_hash` varchar(64) NOT NULL,
	`last_heartbeat_at` timestamp,
	`last_error` text,
	`created_at` timestamp NOT NULL DEFAULT (now()),
	`updated_at` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `file_server_agents_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE INDEX `agent_audit_events_project_idx` ON `agent_audit_events` (`project_id`,`id`);--> statement-breakpoint
CREATE INDEX `file_server_agents_project_idx` ON `file_server_agents` (`project_id`);