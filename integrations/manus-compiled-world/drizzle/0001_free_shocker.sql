CREATE TABLE `source_connections` (
	`id` int AUTO_INCREMENT NOT NULL,
	`project_id` int NOT NULL,
	`provider` enum('google_drive','sharepoint','file_server') NOT NULL,
	`connection_status` enum('setup_required','pending_authorization','active','revoked','error') NOT NULL DEFAULT 'setup_required',
	`scope_summary` varchar(255) NOT NULL,
	`external_root_id` varchar(255),
	`encrypted_access_token` text,
	`encrypted_refresh_token` text,
	`agent_enrollment_hash` varchar(64),
	`last_synced_at` timestamp,
	`created_at` timestamp NOT NULL DEFAULT (now()),
	`updated_at` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `source_connections_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE INDEX `source_connections_project_idx` ON `source_connections` (`project_id`);--> statement-breakpoint
CREATE INDEX `source_connections_provider_idx` ON `source_connections` (`project_id`,`provider`);