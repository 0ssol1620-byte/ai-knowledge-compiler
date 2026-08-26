CREATE TABLE `compile_runs` (
	`id` int AUTO_INCREMENT NOT NULL,
	`project_id` int NOT NULL,
	`compile_status` enum('queued','running','ready','failed') NOT NULL DEFAULT 'queued',
	`stage` varchar(64) NOT NULL DEFAULT 'queued',
	`progress` int NOT NULL DEFAULT 0,
	`result_json` text,
	`error_message` text,
	`created_at` timestamp NOT NULL DEFAULT (now()),
	`completed_at` timestamp,
	CONSTRAINT `compile_runs_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `knowledge_projects` (
	`id` int AUTO_INCREMENT NOT NULL,
	`owner_id` int NOT NULL,
	`name` varchar(160) NOT NULL,
	`created_at` timestamp NOT NULL DEFAULT (now()),
	`updated_at` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `knowledge_projects_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `knowledge_sources` (
	`id` int AUTO_INCREMENT NOT NULL,
	`project_id` int NOT NULL,
	`source_kind` enum('upload','google_drive','sharepoint','file_server','dropbox','demo') NOT NULL,
	`display_name` varchar(255) NOT NULL,
	`mime_type` varchar(160) NOT NULL,
	`byte_size` int NOT NULL,
	`storage_key` varchar(512) NOT NULL,
	`storage_url` varchar(512) NOT NULL,
	`content_hash` varchar(64) NOT NULL,
	`duplicate_of_id` int,
	`source_status` enum('stored','queued','processing','ready','failed') NOT NULL DEFAULT 'stored',
	`created_at` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `knowledge_sources_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `users` (
	`id` int AUTO_INCREMENT NOT NULL,
	`openId` varchar(64) NOT NULL,
	`name` text,
	`email` varchar(320),
	`loginMethod` varchar(64),
	`role` enum('user','admin') NOT NULL DEFAULT 'user',
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	`lastSignedIn` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `users_id` PRIMARY KEY(`id`),
	CONSTRAINT `users_openId_unique` UNIQUE(`openId`)
);
--> statement-breakpoint
CREATE INDEX `compile_runs_project_idx` ON `compile_runs` (`project_id`);--> statement-breakpoint
CREATE INDEX `knowledge_projects_owner_idx` ON `knowledge_projects` (`owner_id`);--> statement-breakpoint
CREATE INDEX `knowledge_sources_project_idx` ON `knowledge_sources` (`project_id`);--> statement-breakpoint
CREATE INDEX `knowledge_sources_hash_idx` ON `knowledge_sources` (`project_id`,`content_hash`);