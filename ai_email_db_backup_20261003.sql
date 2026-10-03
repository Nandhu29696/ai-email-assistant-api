-- MailAI (AI Email Assistant) database backup — FULL (schema + all data)
-- Source: local MySQL 8.0 database `ai_email_db`, taken 2026-10-03.
-- Schema version (alembic): n3b4c5d6e7f8
-- Import into an EMPTY database you created on the server, e.g.:
--   mysql -u USER -p TARGET_DB < ai_email_db_backup_20261003.sql
-- Collation: utf8mb4_unicode_ci (imports on MySQL 5.7+/8.x and MariaDB 10.x).
-- Includes every table's data: users, mailboxes, emails, events, attachments, templates,
-- domains, audit/API logs, login sessions and OAuth states.
-- Contains password hashes, session token hashes and encrypted mailbox tokens: keep this file private.


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
DROP TABLE IF EXISTS `alembic_version`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `alembic_version` (
  `version_num` varchar(32) NOT NULL,
  PRIMARY KEY (`version_num`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `alembic_version` WRITE;
/*!40000 ALTER TABLE `alembic_version` DISABLE KEYS */;
INSERT INTO `alembic_version` VALUES ('n3b4c5d6e7f8');
/*!40000 ALTER TABLE `alembic_version` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `allowed_domains`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `allowed_domains` (
  `id` int NOT NULL AUTO_INCREMENT,
  `domain` varchar(255) NOT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `notes` varchar(500) DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `domain` (`domain`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `allowed_domains` WRITE;
/*!40000 ALTER TABLE `allowed_domains` DISABLE KEYS */;
INSERT INTO `allowed_domains` VALUES (1,'client.com',1,'Demo client','2026-10-03 12:09:05'),(2,'partner.org',1,'Demo partner','2026-10-03 12:09:05'),(3,'gmail.com',1,'Public webmail (testing)','2026-10-03 12:09:05');
/*!40000 ALTER TABLE `allowed_domains` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `api_request_logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `api_request_logs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int DEFAULT NULL,
  `method` varchar(10) DEFAULT NULL,
  `path` varchar(512) DEFAULT NULL,
  `query_params` text,
  `status_code` int DEFAULT NULL,
  `response_time_ms` int DEFAULT NULL,
  `ip_address` varchar(45) DEFAULT NULL,
  `user_agent` varchar(512) DEFAULT NULL,
  `error_detail` text,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_api_request_logs_user_id` (`user_id`),
  KEY `ix_api_request_logs_path` (`path`),
  KEY `ix_api_request_logs_status_code` (`status_code`),
  KEY `ix_api_request_logs_created_at` (`created_at`),
  CONSTRAINT `api_request_logs_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `api_request_logs` WRITE;
/*!40000 ALTER TABLE `api_request_logs` DISABLE KEYS */;
INSERT INTO `api_request_logs` VALUES (1,NULL,'POST','/api/auth/login',NULL,200,692,'127.0.0.1','curl/8.22.0',NULL,'2026-10-03 12:02:48'),(2,NULL,'POST','/api/auth/login',NULL,200,502,'127.0.0.1','curl/8.22.0',NULL,'2026-10-03 12:09:16'),(3,NULL,'POST','/api/auth/login',NULL,401,435,'127.0.0.1','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0',NULL,'2026-10-03 12:33:24'),(4,1,'GET','/api/integrations/gmail/auth-url',NULL,200,2444,'127.0.0.1','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0',NULL,'2026-10-03 12:34:02'),(5,1,'GET','/api/integrations/gmail/callback','state=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwicHJvdmlkZXIiOiJnbWFpbCIsInR5cGUiOiJvYXV0aF9zdGF0ZSIsImp0aSI6Ims1cWxmc1R6U2RzSFUyczdzMHdBbnEtZk44QUlSZWFjIiwiZXhwIjoxNzkxMDExODE5fQ.xKgUac_7uHjFwYtw1oUspnxM_2TFT0ClFapJmwryYto&iss=https%3A%2F%2Faccounts.google.com&code=4%2F0AXlqoi6YFxLVr9qwj238AKXNNBkuSbaCFIG_yI90wcNF48bW-Pz8jRvliWMwd-6PgWIXgQ&scope=email+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.send+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.modify+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email+openid&authuser=4&prompt=consent',307,2380,'127.0.0.1','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0',NULL,'2026-10-03 12:37:17');
/*!40000 ALTER TABLE `api_request_logs` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `audit_logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `audit_logs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int DEFAULT NULL,
  `action` varchar(100) NOT NULL,
  `resource_type` varchar(50) DEFAULT NULL,
  `resource_id` int DEFAULT NULL,
  `ip_address` varchar(45) DEFAULT NULL,
  `user_agent` varchar(512) DEFAULT NULL,
  `status` varchar(20) DEFAULT NULL,
  `details` json DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_audit_logs_user_id` (`user_id`),
  KEY `ix_audit_logs_action` (`action`),
  KEY `ix_audit_logs_created_at` (`created_at`),
  CONSTRAINT `audit_logs_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `audit_logs` WRITE;
/*!40000 ALTER TABLE `audit_logs` DISABLE KEYS */;
INSERT INTO `audit_logs` VALUES (1,1,'login','user',1,'127.0.0.1','curl/8.22.0','success','{\"mfa\": false}','2026-10-03 12:02:48'),(2,1,'login','user',1,'127.0.0.1','curl/8.22.0','success','{\"mfa\": false}','2026-10-03 12:09:16'),(3,1,'login_failed','user',1,'127.0.0.1','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0','failure','{\"reason\": \"password\", \"attempt\": 1}','2026-10-03 12:33:24'),(4,1,'login','user',1,'127.0.0.1','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0','success','{\"mfa\": false}','2026-10-03 12:33:37'),(5,1,'login','user',1,'127.0.0.1','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0','success','{\"mfa\": false}','2026-10-03 12:36:00'),(6,1,'logout','user',1,'127.0.0.1','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0','success','null','2026-10-03 12:36:50'),(7,1,'login','user',1,'127.0.0.1','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0','success','{\"mfa\": false}','2026-10-03 12:36:56');
/*!40000 ALTER TABLE `audit_logs` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `batch_sequences`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `batch_sequences` (
  `id` int NOT NULL AUTO_INCREMENT,
  `sequence_key` varchar(80) NOT NULL,
  `last_value` int NOT NULL DEFAULT '0',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `sequence_key` (`sequence_key`),
  KEY `ix_batch_sequences_key` (`sequence_key`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `batch_sequences` WRITE;
/*!40000 ALTER TABLE `batch_sequences` DISABLE KEYS */;
INSERT INTO `batch_sequences` VALUES (1,'TEST-UAT-20261003',20,'2026-10-03 12:08:45'),(2,'GEN-PROD-20261003',1,'2026-10-03 12:37:41');
/*!40000 ALTER TABLE `batch_sequences` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `category_options`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `category_options` (
  `id` smallint NOT NULL AUTO_INCREMENT,
  `value` varchar(50) NOT NULL,
  `label` varchar(50) NOT NULL,
  `description` text,
  `sort_order` smallint DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `value` (`value`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `category_options` WRITE;
/*!40000 ALTER TABLE `category_options` DISABLE KEYS */;
/*!40000 ALTER TABLE `category_options` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `email_analyses`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `email_analyses` (
  `id` int NOT NULL AUTO_INCREMENT,
  `email_id` int NOT NULL,
  `sentiment` varchar(20) DEFAULT NULL,
  `sentiment_score` decimal(5,4) DEFAULT NULL,
  `primary_emotion` varchar(50) DEFAULT NULL,
  `emotions_json` json DEFAULT NULL,
  `category` varchar(50) DEFAULT NULL,
  `category_confidence` decimal(4,3) DEFAULT NULL,
  `priority` varchar(20) DEFAULT NULL,
  `priority_score` smallint DEFAULT NULL,
  `ai_summary` text,
  `suggested_reply` text,
  `routed_to` varchar(100) DEFAULT NULL,
  `routing_reason` text,
  `model_version` varchar(50) DEFAULT NULL,
  `processing_time_ms` int DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `email_id` (`email_id`),
  CONSTRAINT `email_analyses_ibfk_1` FOREIGN KEY (`email_id`) REFERENCES `emails` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `email_analyses` WRITE;
/*!40000 ALTER TABLE `email_analyses` DISABLE KEYS */;
/*!40000 ALTER TABLE `email_analyses` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `email_batch_attachments`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `email_batch_attachments` (
  `id` int NOT NULL AUTO_INCREMENT,
  `parent_batch_id` int NOT NULL,
  `batch_no` varchar(60) DEFAULT NULL,
  `batch_source_filename` varchar(255) NOT NULL,
  `doc_type` varchar(20) DEFAULT NULL,
  `file_size_bytes` int DEFAULT NULL,
  `received_date` datetime DEFAULT NULL,
  `is_encrypted` tinyint(1) DEFAULT '0',
  `converted_pdf_path` text,
  `status` varchar(20) DEFAULT 'PENDING',
  `status_reason` text,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `parent_batch_id` (`parent_batch_id`),
  KEY `ix_email_batch_attachments_batch_no` (`batch_no`),
  CONSTRAINT `email_batch_attachments_ibfk_1` FOREIGN KEY (`parent_batch_id`) REFERENCES `email_batches` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=21 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `email_batch_attachments` WRITE;
/*!40000 ALTER TABLE `email_batch_attachments` DISABLE KEYS */;
INSERT INTO `email_batch_attachments` VALUES (1,5,'TEST-UAT-20261003-000005','claim_form.pdf','pdf',1843,'2026-09-23 10:08:00',0,'UAT/2026/09/TEST-UAT-20261003-000005/attachments/01_claim_form.pdf','MERGED','Converted, stored and merged','2026-10-03 12:07:27'),(2,6,'TEST-UAT-20261003-000006','invoice.pdf','pdf',1417,'2026-09-23 10:25:00',0,'UAT/2026/09/TEST-UAT-20261003-000006/attachments/01_invoice.pdf','MERGED','Converted, stored and merged','2026-10-03 12:07:31'),(3,6,'TEST-UAT-20261003-000006','receipt.tiff','tiff',115488,'2026-09-23 10:25:00',0,'UAT/2026/09/TEST-UAT-20261003-000006/attachments/02_receipt.pdf','MERGED','Converted, stored and merged','2026-10-03 12:07:31'),(4,7,'TEST-UAT-20261003-000007','claim_form.docx','docx',1123,'2026-09-24 10:42:00',0,'UAT/2026/09/TEST-UAT-20261003-000007/attachments/01_claim_form.pdf','MERGED','Converted, stored and merged','2026-10-03 12:07:35'),(5,8,'TEST-UAT-20261003-000008','form.docx','docx',1123,'2026-09-25 10:59:00',0,'UAT/2026/09/TEST-UAT-20261003-000008/attachments/01_form.pdf','MERGED','Converted, stored and merged','2026-10-03 12:08:15'),(6,8,'TEST-UAT-20261003-000008','invoice.pdf','pdf',2290,'2026-09-25 10:59:00',0,'UAT/2026/09/TEST-UAT-20261003-000008/attachments/02_invoice.pdf','MERGED','Converted, stored and merged','2026-10-03 12:08:15'),(7,8,'TEST-UAT-20261003-000008','photo.tif','tif',57740,'2026-09-25 10:59:00',0,'UAT/2026/09/TEST-UAT-20261003-000008/attachments/03_photo.pdf','MERGED','Converted, stored and merged','2026-10-03 12:08:15'),(8,9,'TEST-UAT-20261003-000009','damage.png','png',12,'2026-09-26 11:16:00',0,NULL,'INVALID_TYPE','File type \'.png\' is not supported. Allowed types: doc, docx, pdf, tif, tiff','2026-10-03 12:08:24'),(9,10,'TEST-UAT-20261003-000010','claim.pdf','pdf',1417,'2026-09-26 11:33:00',0,NULL,'NOT_PROCESSED','Not processed because other attachments are not supported','2026-10-03 12:08:27'),(10,10,'TEST-UAT-20261003-000010','costs.xlsx','xlsx',8,'2026-09-26 11:33:00',0,NULL,'INVALID_TYPE','File type \'.xlsx\' is not supported. Allowed types: doc, docx, pdf, tif, tiff','2026-10-03 12:08:27'),(11,11,'TEST-UAT-20261003-000011','report.pdf','pdf',2098557,'2026-09-27 11:50:00',0,NULL,'INVALID_TYPE','File size 2.0MB exceeds the 1MB limit','2026-10-03 12:08:29'),(12,12,'TEST-UAT-20261003-000012','statement.pdf','pdf',1318,'2026-09-28 12:07:00',1,NULL,'PROTECTED','The PDF is password-protected','2026-10-03 12:08:30'),(13,13,'TEST-UAT-20261003-000013','form.docx','docx',6656,'2026-09-28 12:24:00',1,NULL,'PROTECTED','The Word document is password-protected','2026-10-03 12:08:33'),(14,14,'TEST-UAT-20261003-000014','claim.pdf','pdf',21,'2026-09-29 12:41:00',0,NULL,'UNREADABLE','The PDF is damaged or not a valid PDF file','2026-10-03 12:08:35'),(15,15,'TEST-UAT-20261003-000015','invoice.pdf','pdf',1417,'2026-09-30 12:58:00',0,NULL,'NOT_PROCESSED','Not processed because other attachments could not be opened','2026-10-03 12:08:36'),(16,15,'TEST-UAT-20261003-000015','scan.tiff','tiff',10,'2026-09-30 12:58:00',0,NULL,'UNREADABLE','The image is damaged or not a valid TIFF file','2026-10-03 12:08:36'),(17,16,'TEST-UAT-20261003-000016','document.pdf','pdf',0,'2026-09-30 13:15:00',0,NULL,'UNREADABLE','The file is empty','2026-10-03 12:08:38'),(18,17,'TEST-UAT-20261003-000017','Facture_été.PDF','pdf',1417,'2026-10-01 13:32:00',0,'UAT/2026/10/TEST-UAT-20261003-000017/attachments/01_Facture__t.pdf','MERGED','Converted, stored and merged','2026-10-03 12:08:40'),(19,20,'TEST-UAT-20261003-000020','final.pdf','pdf',1407,'2026-10-03 06:37:45',0,'UAT/2026/10/TEST-UAT-20261003-000020/attachments/01_final.pdf','MERGED','Converted, stored and merged','2026-10-03 12:08:46'),(20,20,'TEST-UAT-20261003-000020','scan.tiff','tiff',57740,'2026-10-03 06:37:45',0,'UAT/2026/10/TEST-UAT-20261003-000020/attachments/02_scan.pdf','MERGED','Converted, stored and merged','2026-10-03 12:08:46');
/*!40000 ALTER TABLE `email_batch_attachments` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `email_batch_callbacks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `email_batch_callbacks` (
  `id` int NOT NULL AUTO_INCREMENT,
  `parent_batch_id` int NOT NULL,
  `batch_no` varchar(60) DEFAULT NULL,
  `process_result_status_code` varchar(20) DEFAULT NULL,
  `process_result_message` text,
  `payload_json` json DEFAULT NULL,
  `webhook_url` text,
  `http_status_code` int DEFAULT NULL,
  `attempt_no` smallint DEFAULT '1',
  `delivered` tinyint(1) DEFAULT '0',
  `error_detail` text,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `parent_batch_id` (`parent_batch_id`),
  KEY `ix_email_batch_callbacks_batch_no` (`batch_no`),
  CONSTRAINT `email_batch_callbacks_ibfk_1` FOREIGN KEY (`parent_batch_id`) REFERENCES `email_batches` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `email_batch_callbacks` WRITE;
/*!40000 ALTER TABLE `email_batch_callbacks` DISABLE KEYS */;
/*!40000 ALTER TABLE `email_batch_callbacks` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `email_batch_events`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `email_batch_events` (
  `id` int NOT NULL AUTO_INCREMENT,
  `parent_batch_id` int NOT NULL,
  `batch_no` varchar(60) DEFAULT NULL,
  `event_type` varchar(40) NOT NULL,
  `related_filename` varchar(255) DEFAULT NULL,
  `reply_sent` tinyint(1) DEFAULT '0',
  `reply_message_id` varchar(512) DEFAULT NULL,
  `details` json DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `parent_batch_id` (`parent_batch_id`),
  KEY `ix_email_batch_events_batch_no` (`batch_no`),
  CONSTRAINT `email_batch_events_ibfk_1` FOREIGN KEY (`parent_batch_id`) REFERENCES `email_batches` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=98 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `email_batch_events` WRITE;
/*!40000 ALTER TABLE `email_batch_events` DISABLE KEYS */;
INSERT INTO `email_batch_events` VALUES (1,1,'TEST-UAT-20261003-000001','RECEIVED',NULL,0,NULL,'{\"from\": \"billing@unknownshop.net\"}','2026-10-03 12:06:18'),(2,1,'TEST-UAT-20261003-000001','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"invoice\", \"priority\": \"low\", \"sentiment\": \"positive\"}','2026-10-03 12:06:19'),(3,1,'TEST-UAT-20261003-000001','DOMAIN_REJECTED',NULL,1,NULL,'{\"domain\": \"unknownshop.net\", \"template\": \"domain_rejected\"}','2026-10-03 12:06:19'),(4,2,'TEST-UAT-20261003-000002','RECEIVED',NULL,0,NULL,'{\"from\": \"claims@evilclient.com\"}','2026-10-03 12:06:20'),(5,2,'TEST-UAT-20261003-000002','ANALYZED',NULL,0,NULL,'{\"emotion\": \"urgency\", \"category\": \"general\", \"priority\": \"medium\", \"sentiment\": \"positive\"}','2026-10-03 12:07:21'),(6,2,'TEST-UAT-20261003-000002','DOMAIN_REJECTED',NULL,1,NULL,'{\"domain\": \"evilclient.com\", \"template\": \"domain_rejected\"}','2026-10-03 12:07:21'),(7,3,'TEST-UAT-20261003-000003','RECEIVED',NULL,0,NULL,'{\"from\": \"ops@mail.client.com\"}','2026-10-03 12:07:21'),(8,3,'TEST-UAT-20261003-000003','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"support\", \"priority\": \"low\", \"sentiment\": \"positive\"}','2026-10-03 12:07:23'),(9,3,'TEST-UAT-20261003-000003','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:07:23'),(10,3,'TEST-UAT-20261003-000003','NO_ATTACHMENT',NULL,1,NULL,'{\"template\": \"no_attachment\"}','2026-10-03 12:07:23'),(11,4,'TEST-UAT-20261003-000004','RECEIVED',NULL,0,NULL,'{\"from\": \"alice@client.com\"}','2026-10-03 12:07:23'),(12,4,'TEST-UAT-20261003-000004','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"general\", \"priority\": \"low\", \"sentiment\": \"positive\"}','2026-10-03 12:07:25'),(13,4,'TEST-UAT-20261003-000004','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:07:25'),(14,4,'TEST-UAT-20261003-000004','NO_ATTACHMENT',NULL,1,NULL,'{\"template\": \"no_attachment\"}','2026-10-03 12:07:25'),(15,5,'TEST-UAT-20261003-000005','RECEIVED',NULL,0,NULL,'{\"from\": \"bob@client.com\"}','2026-10-03 12:07:26'),(16,5,'TEST-UAT-20261003-000005','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"support\", \"priority\": \"low\", \"sentiment\": \"positive\"}','2026-10-03 12:07:27'),(17,5,'TEST-UAT-20261003-000005','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:07:27'),(18,5,'TEST-UAT-20261003-000005','ATTACHMENTS_CONVERTED',NULL,0,NULL,'{\"count\": 1}','2026-10-03 12:07:28'),(19,5,'TEST-UAT-20261003-000005','EMAIL_PDF_CREATED',NULL,0,NULL,'{}','2026-10-03 12:07:28'),(20,5,'TEST-UAT-20261003-000005','MERGED_PDF_STORED',NULL,0,NULL,'{\"pages_from\": 2}','2026-10-03 12:07:28'),(21,5,'TEST-UAT-20261003-000005','SUCCESS_REPLY',NULL,1,NULL,'{\"template\": \"success\"}','2026-10-03 12:07:28'),(22,6,'TEST-UAT-20261003-000006','RECEIVED',NULL,0,NULL,'{\"from\": \"carol@partner.org\"}','2026-10-03 12:07:31'),(23,6,'TEST-UAT-20261003-000006','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"invoice\", \"priority\": \"medium\", \"sentiment\": \"neutral\"}','2026-10-03 12:07:31'),(24,6,'TEST-UAT-20261003-000006','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:07:31'),(25,6,'TEST-UAT-20261003-000006','ATTACHMENTS_CONVERTED',NULL,0,NULL,'{\"count\": 2}','2026-10-03 12:07:31'),(26,6,'TEST-UAT-20261003-000006','EMAIL_PDF_CREATED',NULL,0,NULL,'{}','2026-10-03 12:07:32'),(27,6,'TEST-UAT-20261003-000006','MERGED_PDF_STORED',NULL,0,NULL,'{\"pages_from\": 3}','2026-10-03 12:07:32'),(28,6,'TEST-UAT-20261003-000006','SUCCESS_REPLY',NULL,1,NULL,'{\"template\": \"success\"}','2026-10-03 12:07:32'),(29,7,'TEST-UAT-20261003-000007','RECEIVED',NULL,0,NULL,'{\"from\": \"dave@client.com\"}','2026-10-03 12:07:33'),(30,7,'TEST-UAT-20261003-000007','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"general\", \"priority\": \"low\", \"sentiment\": \"neutral\"}','2026-10-03 12:07:35'),(31,7,'TEST-UAT-20261003-000007','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:07:35'),(32,7,'TEST-UAT-20261003-000007','ATTACHMENTS_CONVERTED',NULL,0,NULL,'{\"count\": 1}','2026-10-03 12:08:14'),(33,7,'TEST-UAT-20261003-000007','EMAIL_PDF_CREATED',NULL,0,NULL,'{}','2026-10-03 12:08:14'),(34,7,'TEST-UAT-20261003-000007','MERGED_PDF_STORED',NULL,0,NULL,'{\"pages_from\": 2}','2026-10-03 12:08:14'),(35,7,'TEST-UAT-20261003-000007','SUCCESS_REPLY',NULL,1,NULL,'{\"template\": \"success\"}','2026-10-03 12:08:14'),(36,8,'TEST-UAT-20261003-000008','RECEIVED',NULL,0,NULL,'{\"from\": \"erin@client.com\"}','2026-10-03 12:08:15'),(37,8,'TEST-UAT-20261003-000008','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"invoice\", \"priority\": \"medium\", \"sentiment\": \"neutral\"}','2026-10-03 12:08:15'),(38,8,'TEST-UAT-20261003-000008','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:08:15'),(39,8,'TEST-UAT-20261003-000008','ATTACHMENTS_CONVERTED',NULL,0,NULL,'{\"count\": 3}','2026-10-03 12:08:22'),(40,8,'TEST-UAT-20261003-000008','EMAIL_PDF_CREATED',NULL,0,NULL,'{}','2026-10-03 12:08:22'),(41,8,'TEST-UAT-20261003-000008','MERGED_PDF_STORED',NULL,0,NULL,'{\"pages_from\": 4}','2026-10-03 12:08:22'),(42,8,'TEST-UAT-20261003-000008','SUCCESS_REPLY',NULL,1,NULL,'{\"template\": \"success\"}','2026-10-03 12:08:23'),(43,9,'TEST-UAT-20261003-000009','RECEIVED',NULL,0,NULL,'{\"from\": \"frank@client.com\"}','2026-10-03 12:08:23'),(44,9,'TEST-UAT-20261003-000009','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"general\", \"priority\": \"medium\", \"sentiment\": \"negative\"}','2026-10-03 12:08:24'),(45,9,'TEST-UAT-20261003-000009','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:08:24'),(46,9,'TEST-UAT-20261003-000009','INVALID_FILE_TYPE',NULL,1,NULL,'{\"files\": [\"damage.png\"], \"template\": \"invalid_file_type\"}','2026-10-03 12:08:25'),(47,10,'TEST-UAT-20261003-000010','RECEIVED',NULL,0,NULL,'{\"from\": \"grace@partner.org\"}','2026-10-03 12:08:26'),(48,10,'TEST-UAT-20261003-000010','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"general\", \"priority\": \"low\", \"sentiment\": \"neutral\"}','2026-10-03 12:08:27'),(49,10,'TEST-UAT-20261003-000010','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:08:27'),(50,10,'TEST-UAT-20261003-000010','INVALID_FILE_TYPE',NULL,1,NULL,'{\"files\": [\"costs.xlsx\"], \"template\": \"invalid_file_type\"}','2026-10-03 12:08:27'),(51,11,'TEST-UAT-20261003-000011','RECEIVED',NULL,0,NULL,'{\"from\": \"heidi@client.com\"}','2026-10-03 12:08:28'),(52,11,'TEST-UAT-20261003-000011','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"support\", \"priority\": \"medium\", \"sentiment\": \"neutral\"}','2026-10-03 12:08:29'),(53,11,'TEST-UAT-20261003-000011','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:08:29'),(54,11,'TEST-UAT-20261003-000011','INVALID_FILE_TYPE',NULL,1,NULL,'{\"files\": [\"report.pdf\"], \"template\": \"invalid_file_type\"}','2026-10-03 12:08:29'),(55,12,'TEST-UAT-20261003-000012','RECEIVED',NULL,0,NULL,'{\"from\": \"ivan@client.com\"}','2026-10-03 12:08:30'),(56,12,'TEST-UAT-20261003-000012','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"invoice\", \"priority\": \"medium\", \"sentiment\": \"neutral\"}','2026-10-03 12:08:30'),(57,12,'TEST-UAT-20261003-000012','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:08:30'),(58,12,'TEST-UAT-20261003-000012','INVALID_ATTACHMENTS',NULL,1,NULL,'{\"files\": [\"statement.pdf\"], \"template\": \"invalid_attachments\"}','2026-10-03 12:08:30'),(59,13,'TEST-UAT-20261003-000013','RECEIVED',NULL,0,NULL,'{\"from\": \"judy@partner.org\"}','2026-10-03 12:08:31'),(60,13,'TEST-UAT-20261003-000013','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"general\", \"priority\": \"low\", \"sentiment\": \"positive\"}','2026-10-03 12:08:33'),(61,13,'TEST-UAT-20261003-000013','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:08:33'),(62,13,'TEST-UAT-20261003-000013','INVALID_ATTACHMENTS',NULL,1,NULL,'{\"files\": [\"form.docx\"], \"template\": \"invalid_attachments\"}','2026-10-03 12:08:33'),(63,14,'TEST-UAT-20261003-000014','RECEIVED',NULL,0,NULL,'{\"from\": \"ken@client.com\"}','2026-10-03 12:08:34'),(64,14,'TEST-UAT-20261003-000014','ANALYZED',NULL,0,NULL,'{\"emotion\": \"frustration\", \"category\": \"complaint\", \"priority\": \"critical\", \"sentiment\": \"negative\"}','2026-10-03 12:08:35'),(65,14,'TEST-UAT-20261003-000014','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:08:35'),(66,14,'TEST-UAT-20261003-000014','INVALID_ATTACHMENTS',NULL,1,NULL,'{\"files\": [\"claim.pdf\"], \"template\": \"invalid_attachments\"}','2026-10-03 12:08:35'),(67,15,'TEST-UAT-20261003-000015','RECEIVED',NULL,0,NULL,'{\"from\": \"laura@client.com\"}','2026-10-03 12:08:36'),(68,15,'TEST-UAT-20261003-000015','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"invoice\", \"priority\": \"medium\", \"sentiment\": \"neutral\"}','2026-10-03 12:08:36'),(69,15,'TEST-UAT-20261003-000015','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:08:36'),(70,15,'TEST-UAT-20261003-000015','INVALID_ATTACHMENTS',NULL,1,NULL,'{\"files\": [\"scan.tiff\"], \"template\": \"invalid_attachments\"}','2026-10-03 12:08:36'),(71,16,'TEST-UAT-20261003-000016','RECEIVED',NULL,0,NULL,'{\"from\": \"mike@client.com\"}','2026-10-03 12:08:37'),(72,16,'TEST-UAT-20261003-000016','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"general\", \"priority\": \"medium\", \"sentiment\": \"negative\"}','2026-10-03 12:08:38'),(73,16,'TEST-UAT-20261003-000016','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:08:38'),(74,16,'TEST-UAT-20261003-000016','INVALID_ATTACHMENTS',NULL,1,NULL,'{\"files\": [\"document.pdf\"], \"template\": \"invalid_attachments\"}','2026-10-03 12:08:38'),(75,17,'TEST-UAT-20261003-000017','RECEIVED',NULL,0,NULL,'{\"from\": \"nora@partner.org\"}','2026-10-03 12:08:38'),(76,17,'TEST-UAT-20261003-000017','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"general\", \"priority\": \"low\", \"sentiment\": \"neutral\"}','2026-10-03 12:08:40'),(77,17,'TEST-UAT-20261003-000017','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:08:40'),(78,17,'TEST-UAT-20261003-000017','ATTACHMENTS_CONVERTED',NULL,0,NULL,'{\"count\": 1}','2026-10-03 12:08:40'),(79,17,'TEST-UAT-20261003-000017','EMAIL_PDF_CREATED',NULL,0,NULL,'{}','2026-10-03 12:08:40'),(80,17,'TEST-UAT-20261003-000017','MERGED_PDF_STORED',NULL,0,NULL,'{\"pages_from\": 2}','2026-10-03 12:08:40'),(81,17,'TEST-UAT-20261003-000017','SUCCESS_REPLY',NULL,1,NULL,'{\"template\": \"success\"}','2026-10-03 12:08:40'),(82,18,'TEST-UAT-20261003-000018','RECEIVED',NULL,0,NULL,'{\"from\": \"oscar@client.com\"}','2026-10-03 12:08:41'),(83,18,'TEST-UAT-20261003-000018','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"general\", \"priority\": \"low\", \"sentiment\": \"neutral\"}','2026-10-03 12:08:42'),(84,18,'TEST-UAT-20261003-000018','AUTOMATED_MESSAGE_IGNORED',NULL,0,NULL,'{}','2026-10-03 12:08:42'),(85,19,'TEST-UAT-20261003-000019','RECEIVED',NULL,0,NULL,'{\"from\": \"ceo@client.com\"}','2026-10-03 12:08:42'),(86,19,'TEST-UAT-20261003-000019','ANALYZED',NULL,0,NULL,'{\"emotion\": \"urgency\", \"category\": \"complaint\", \"priority\": \"critical\", \"sentiment\": \"positive\"}','2026-10-03 12:08:44'),(87,19,'TEST-UAT-20261003-000019','SENDER_NOT_VERIFIED',NULL,0,NULL,'{}','2026-10-03 12:08:44'),(88,20,'TEST-UAT-20261003-000020','RECEIVED',NULL,0,NULL,'{\"from\": \"paul@client.com\"}','2026-10-03 12:08:45'),(89,20,'TEST-UAT-20261003-000020','ANALYZED',NULL,0,NULL,'{\"emotion\": \"satisfaction\", \"category\": \"support\", \"priority\": \"low\", \"sentiment\": \"positive\"}','2026-10-03 12:08:46'),(90,20,'TEST-UAT-20261003-000020','ACKNOWLEDGEMENT_SENT',NULL,1,NULL,'{\"template\": \"acknowledgement\"}','2026-10-03 12:08:46'),(91,20,'TEST-UAT-20261003-000020','ATTACHMENTS_CONVERTED',NULL,0,NULL,'{\"count\": 2}','2026-10-03 12:08:46'),(92,20,'TEST-UAT-20261003-000020','EMAIL_PDF_CREATED',NULL,0,NULL,'{}','2026-10-03 12:08:47'),(93,20,'TEST-UAT-20261003-000020','MERGED_PDF_STORED',NULL,0,NULL,'{\"pages_from\": 3}','2026-10-03 12:08:47'),(94,20,'TEST-UAT-20261003-000020','SUCCESS_REPLY',NULL,1,NULL,'{\"template\": \"success\"}','2026-10-03 12:08:47'),(95,21,'GEN-PROD-20261003-000001','RECEIVED',NULL,0,NULL,'{\"from\": \"no-reply@accounts.google.com\"}','2026-10-03 12:37:42'),(96,21,'GEN-PROD-20261003-000001','ANALYZED',NULL,0,NULL,'{\"emotion\": \"neutral\", \"category\": \"general\", \"priority\": \"low\", \"sentiment\": \"positive\"}','2026-10-03 12:38:10'),(97,21,'GEN-PROD-20261003-000001','AUTOMATED_MESSAGE_IGNORED',NULL,0,NULL,'{}','2026-10-03 12:38:10');
/*!40000 ALTER TABLE `email_batch_events` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `email_batches`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `email_batches` (
  `id` int NOT NULL AUTO_INCREMENT,
  `batch_no` varchar(60) NOT NULL,
  `message_id` varchar(512) NOT NULL,
  `conversation_id` varchar(512) DEFAULT NULL,
  `integration_id` int DEFAULT NULL,
  `mailbox_type` varchar(10) DEFAULT NULL,
  `email_type` varchar(30) DEFAULT 'inbound_document',
  `sender_email` varchar(255) NOT NULL,
  `recipient_email` varchar(255) DEFAULT NULL,
  `subject` text,
  `received_datetime` datetime NOT NULL,
  `status` varchar(30) DEFAULT 'RECEIVED',
  `status_reason` text,
  `attachment_count` int DEFAULT '0',
  `merged_pdf_path` text,
  `sentiment` varchar(20) DEFAULT NULL,
  `sentiment_score` decimal(5,4) DEFAULT NULL,
  `primary_emotion` varchar(50) DEFAULT NULL,
  `email_category` varchar(50) DEFAULT NULL,
  `sensitivity_level` varchar(20) DEFAULT NULL,
  `contains_pii` tinyint(1) DEFAULT '0',
  `pii_types_json` json DEFAULT NULL,
  `ai_model_version` varchar(50) DEFAULT NULL,
  `processed_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `is_archived` tinyint(1) DEFAULT '0',
  `archived_at` datetime DEFAULT NULL,
  `sender_name` varchar(255) DEFAULT NULL,
  `body_text` text,
  `outcome` varchar(40) DEFAULT NULL,
  `email_pdf_path` text,
  `priority` varchar(20) DEFAULT NULL,
  `ai_summary` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `batch_no` (`batch_no`),
  UNIQUE KEY `uq_email_batches_integration_message` (`integration_id`,`message_id`),
  KEY `ix_email_batches_batch_no` (`batch_no`),
  KEY `ix_email_batches_message_id` (`message_id`),
  KEY `ix_email_batches_status` (`status`),
  KEY `ix_email_batches_received_datetime` (`received_datetime`),
  KEY `ix_email_batches_is_archived` (`is_archived`),
  KEY `ix_email_batches_outcome` (`outcome`),
  KEY `ix_email_batches_priority` (`priority`),
  CONSTRAINT `email_batches_ibfk_1` FOREIGN KEY (`integration_id`) REFERENCES `email_integrations` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=22 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `email_batches` WRITE;
/*!40000 ALTER TABLE `email_batches` DISABLE KEYS */;
INSERT INTO `email_batches` VALUES (1,'TEST-UAT-20261003-000001','<test-intake-01@mailai.local>','test-1',2,'UAT','inbound_document','billing@unknownshop.net','testfsl551@gmail.com','[TEST] Invoice from an unknown company','2026-09-20 09:00:00','REJECTED','Sender domain \'unknownshop.net\' not permitted as per policy',0,NULL,'positive',0.3182,'neutral','invoice',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:36:20','2026-10-03 12:06:18','2026-10-03 12:40:48',0,NULL,'Billing','Please find attached the invoice for your recent order.','DOMAIN_NOT_ALLOWED',NULL,'low','Please find attached the invoice for your recent order.'),(2,'TEST-UAT-20261003-000002','<test-intake-02@mailai.local>','test-2',2,'UAT','inbound_document','claims@evilclient.com','testfsl551@gmail.com','[TEST] Look-alike domain','2026-09-21 09:17:00','REJECTED','Sender domain \'evilclient.com\' not permitted as per policy',0,NULL,'positive',0.2023,'urgency','general',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:37:21','2026-10-03 12:06:19','2026-10-03 12:40:48',0,NULL,'Claims','Urgent: submit these documents now.','DOMAIN_NOT_ALLOWED',NULL,'medium','Urgent: submit these documents now.'),(3,'TEST-UAT-20261003-000003','<test-intake-03@mailai.local>','test-3',2,'UAT','inbound_document','ops@mail.client.com','testfsl551@gmail.com','[TEST] Sub-domain of a client, no attachment','2026-09-21 09:34:00','REJECTED','The email has no attachment to process',0,NULL,'positive',0.1561,'neutral','support',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:37:24','2026-10-03 12:07:21','2026-10-03 12:40:48',0,NULL,'Ops','Hi, I would like to submit a claim. What do you need from me?','NO_ATTACHMENT',NULL,'low','Hi, I would like to submit a claim. What do you need from me?'),(4,'TEST-UAT-20261003-000004','<test-intake-04@mailai.local>','test-4',2,'UAT','inbound_document','alice@client.com','testfsl551@gmail.com','[TEST] Forgot the attachment','2026-09-22 09:51:00','REJECTED','The email has no attachment to process',0,NULL,'positive',0.6588,'neutral','general',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:37:26','2026-10-03 12:07:23','2026-10-03 12:40:48',0,NULL,'Alice','Hello team, attached is my claim form. Thanks!','NO_ATTACHMENT',NULL,'low','Hello team, attached is my claim form. Thanks!'),(5,'TEST-UAT-20261003-000005','<test-intake-05@mailai.local>','test-5',2,'UAT','inbound_document','bob@client.com','testfsl551@gmail.com','[TEST] Single PDF claim','2026-09-23 10:08:00','SUCCESS','1 attachment(s) converted, merged and stored',1,'UAT/2026/09/TEST-UAT-20261003-000005/TEST-UAT-20261003-000005_merged.pdf','positive',0.8074,'neutral','support',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:37:29','2026-10-03 12:07:25','2026-10-03 12:44:17',0,NULL,'Bob','Dear team, please process the attached claim. Kind regards, Bob','PROCESSED','UAT/2026/09/TEST-UAT-20261003-000005/email_content.pdf','low','Dear team, please process the attached claim. Kind regards, Bob'),(6,'TEST-UAT-20261003-000006','<test-intake-06@mailai.local>','test-6',2,'UAT','inbound_document','carol@partner.org','testfsl551@gmail.com','[TEST] PDF and scanned TIFF','2026-09-23 10:25:00','SUCCESS','2 attachment(s) converted, merged and stored',2,'UAT/2026/09/TEST-UAT-20261003-000006/TEST-UAT-20261003-000006_merged.pdf','neutral',0.0000,'neutral','invoice',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:37:33','2026-10-03 12:07:30','2026-10-03 12:44:17',0,NULL,'Carol','Attached are the invoice and the scanned receipt.','PROCESSED','UAT/2026/09/TEST-UAT-20261003-000006/email_content.pdf','medium','Attached are the invoice and the scanned receipt.'),(7,'TEST-UAT-20261003-000007','<test-intake-07@mailai.local>','test-7',2,'UAT','inbound_document','dave@client.com','testfsl551@gmail.com','[TEST] Word claim form','2026-09-24 10:42:00','SUCCESS','1 attachment(s) converted, merged and stored',1,'UAT/2026/09/TEST-UAT-20261003-000007/TEST-UAT-20261003-000007_merged.pdf','neutral',0.0000,'neutral','general',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:15','2026-10-03 12:07:33','2026-10-03 12:44:17',0,NULL,'Dave','Here is the completed claim form in Word format.','PROCESSED','UAT/2026/09/TEST-UAT-20261003-000007/email_content.pdf','low','Here is the completed claim form in Word format.'),(8,'TEST-UAT-20261003-000008','<test-intake-08@mailai.local>','test-8',2,'UAT','inbound_document','erin@client.com','testfsl551@gmail.com','[TEST] Three documents at once','2026-09-25 10:59:00','SUCCESS','3 attachment(s) converted, merged and stored',3,'UAT/2026/09/TEST-UAT-20261003-000008/TEST-UAT-20261003-000008_merged.pdf','neutral',0.0000,'neutral','invoice',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:23','2026-10-03 12:08:15','2026-10-03 12:44:17',0,NULL,'Erin','Sending all three documents for claim 5512: form, invoice and photo scan.','PROCESSED','UAT/2026/09/TEST-UAT-20261003-000008/email_content.pdf','medium','Sending all three documents for claim 5512: form, invoice and photo scan.'),(9,'TEST-UAT-20261003-000009','<test-intake-09@mailai.local>','test-9',2,'UAT','inbound_document','frank@client.com','testfsl551@gmail.com','[TEST] Only a photo (PNG)','2026-09-26 11:16:00','REJECTED','Unsupported attachment(s): damage.png',1,NULL,'negative',-0.4939,'neutral','general',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:25','2026-10-03 12:08:23','2026-10-03 12:40:48',0,NULL,'Frank','Photo of the damage attached.','INVALID_FILE_TYPE',NULL,'medium','Photo of the damage attached.'),(10,'TEST-UAT-20261003-000010','<test-intake-10@mailai.local>','test-10',2,'UAT','inbound_document','grace@partner.org','testfsl551@gmail.com','[TEST] PDF plus a spreadsheet','2026-09-26 11:33:00','REJECTED','Unsupported attachment(s): costs.xlsx',2,NULL,'neutral',0.0000,'neutral','general',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:28','2026-10-03 12:08:25','2026-10-03 12:40:48',0,NULL,'Grace','Claim attached plus the cost breakdown spreadsheet.','INVALID_FILE_TYPE',NULL,'low','Claim attached plus the cost breakdown spreadsheet.'),(11,'TEST-UAT-20261003-000011','<test-intake-11@mailai.local>','test-11',2,'UAT','inbound_document','heidi@client.com','testfsl551@gmail.com','[TEST] File too large','2026-09-27 11:50:00','REJECTED','Unsupported attachment(s): report.pdf',1,NULL,'neutral',0.0000,'neutral','support',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:30','2026-10-03 12:08:27','2026-10-03 12:40:48',0,NULL,'Heidi','Attached is the full medical report.','INVALID_FILE_TYPE',NULL,'medium','Attached is the full medical report.'),(12,'TEST-UAT-20261003-000012','<test-intake-12@mailai.local>','test-12',2,'UAT','inbound_document','ivan@client.com','testfsl551@gmail.com','[TEST] Password-protected bank statement','2026-09-28 12:07:00','REJECTED','Attachment(s) protected or unreadable: statement.pdf',1,NULL,'neutral',0.0000,'neutral','invoice',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:31','2026-10-03 12:08:30','2026-10-03 12:40:48',0,NULL,'Ivan','My bank statement is attached (password is my date of birth).','INVALID_ATTACHMENTS',NULL,'medium','My bank statement is attached (password is my date of birth).'),(13,'TEST-UAT-20261003-000013','<test-intake-13@mailai.local>','test-13',2,'UAT','inbound_document','judy@partner.org','testfsl551@gmail.com','[TEST] Password-protected Word file','2026-09-28 12:24:00','REJECTED','Attachment(s) protected or unreadable: form.docx',1,NULL,'positive',0.4404,'neutral','general',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:34','2026-10-03 12:08:31','2026-10-03 12:40:48',0,NULL,'Judy','Protected form attached as requested.','INVALID_ATTACHMENTS',NULL,'low','Protected form attached as requested.'),(14,'TEST-UAT-20261003-000014','<test-intake-14@mailai.local>','test-14',2,'UAT','inbound_document','ken@client.com','testfsl551@gmail.com','[TEST] Damaged PDF','2026-09-29 12:41:00','REJECTED','Attachment(s) protected or unreadable: claim.pdf',1,NULL,'negative',-0.7495,'frustration','complaint',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:36','2026-10-03 12:08:33','2026-10-03 12:40:48',0,NULL,'Ken','This is the third time I am sending this, very frustrating!','INVALID_ATTACHMENTS',NULL,'critical','This is the third time I am sending this, very frustrating!'),(15,'TEST-UAT-20261003-000015','<test-intake-15@mailai.local>','test-15',2,'UAT','inbound_document','laura@client.com','testfsl551@gmail.com','[TEST] Good PDF with a damaged scan','2026-09-30 12:58:00','REJECTED','Attachment(s) protected or unreadable: scan.tiff',2,NULL,'neutral',0.0000,'neutral','invoice',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:37','2026-10-03 12:08:36','2026-10-03 12:40:48',0,NULL,'Laura','Invoice and scan attached.','INVALID_ATTACHMENTS',NULL,'medium','Invoice and scan attached.'),(16,'TEST-UAT-20261003-000016','<test-intake-16@mailai.local>','test-16',2,'UAT','inbound_document','mike@client.com','testfsl551@gmail.com','[TEST] Empty file','2026-09-30 13:15:00','REJECTED','Attachment(s) protected or unreadable: document.pdf',1,NULL,'negative',-0.2023,'neutral','general',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:38','2026-10-03 12:08:37','2026-10-03 12:40:48',0,NULL,'Mike','Document attached.','INVALID_ATTACHMENTS',NULL,'medium','Document attached.'),(17,'TEST-UAT-20261003-000017','<test-intake-17@mailai.local>','test-17',2,'UAT','inbound_document','nora@partner.org','testfsl551@gmail.com','[TEST] Upper-case extension and accented name','2026-10-01 13:32:00','SUCCESS','1 attachment(s) converted, merged and stored',1,'UAT/2026/10/TEST-UAT-20261003-000017/TEST-UAT-20261003-000017_merged.pdf','neutral',0.0000,'neutral','general',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:41','2026-10-03 12:08:38','2026-10-03 12:44:17',0,NULL,'Nora','Bonjour, veuillez trouver la facture ci-jointe. Merci beaucoup !','PROCESSED','UAT/2026/10/TEST-UAT-20261003-000017/email_content.pdf','low','Bonjour, veuillez trouver la facture ci-jointe. Merci beaucoup !'),(18,'TEST-UAT-20261003-000018','<test-intake-18@mailai.local>','test-18',2,'UAT','inbound_document','oscar@client.com','testfsl551@gmail.com','[TEST] Out-of-office auto reply','2026-10-02 13:49:00','IGNORED','Automated message (bounce, out-of-office or mailing list) — no reply sent',0,NULL,'neutral',0.0000,'neutral','general',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:42','2026-10-03 12:08:40','2026-10-03 12:40:48',0,NULL,'Oscar','I am out of the office until Monday.','AUTOMATED_MESSAGE',NULL,'low','I am out of the office until Monday.'),(19,'TEST-UAT-20261003-000019','<test-intake-19@mailai.local>','test-19',2,'UAT','inbound_document','ceo@client.com','testfsl551@gmail.com','[TEST] Forged sender','2026-10-02 14:06:00','REJECTED','Sender could not be verified (SPF/DKIM/DMARC failed) — not processed, no reply sent',0,NULL,'positive',0.4767,'urgency','complaint',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:45','2026-10-03 12:08:42','2026-10-03 12:40:48',0,NULL,'Ceo','Please process this urgent payment request.','SENDER_NOT_VERIFIED',NULL,'critical','Please process this urgent payment request.'),(20,'TEST-UAT-20261003-000020','<test-intake-20@mailai.local>','test-20',2,'UAT','inbound_document','paul@client.com','testfsl551@gmail.com','[TEST] Same-day complete submission','2026-10-03 06:37:45','SUCCESS','2 attachment(s) converted, merged and stored',2,'UAT/2026/10/TEST-UAT-20261003-000020/TEST-UAT-20261003-000020_merged.pdf','positive',0.6696,'satisfaction','support',NULL,0,NULL,'llama3.2:latest','2026-10-03 06:38:48','2026-10-03 12:08:45','2026-10-03 12:44:17',0,NULL,'Paul','Thank you for the quick help last time! Attached are the final documents.','PROCESSED','UAT/2026/10/TEST-UAT-20261003-000020/email_content.pdf','low','Thank you for the quick help last time! Attached are the final documents.'),(21,'GEN-PROD-20261003-000001','Dwur29lPmCIvx7Pab4RnRg@notifications.google.com','1a10096b29601653',2,'PROD','inbound_document','no-reply@accounts.google.com','testfsl551@gmail.com','Security alert','2026-10-03 07:07:17','IGNORED','Automated message (bounce, out-of-office or mailing list) — no reply sent',0,NULL,'positive',0.9013,'neutral','general',NULL,0,NULL,'llama3.2:latest','2026-10-03 07:08:10','2026-10-03 12:37:41','2026-10-03 12:38:10',0,NULL,'Google','[image: Google]\r\nYou allowed testmail access to some of your Google Account data\r\n\r\n\r\ntestfsl551@gmail.com\r\n\r\nIf you didn’t allow testmail access to some of your Google Account data,\r\nsomeone else may be trying to access your Google Account data.\r\n\r\nTake a moment now to check your account activity and secure your account.\r\nCheck activity\r\n<https://accounts.google.com/AccountChooser?Email=testfsl551@gmail.com&continue=https://myaccount.google.com/alert/nt/1791011237000?rfn%3D127%26rfnc%3D1%26eid%3D6336039801952152903%26et%3D0>\r\nTo make changes at any time to the access that testmail has to your data,\r\ngo to your Google Account\r\n<https://accounts.google.com/AccountChooser?Email=testfsl551@gmail.com&continue=https://myaccount.google.com/connections/overview/AREUMUXrm6PqIFs4xD9jPAvChAAljBfD9j3M_T04pXt9daZ2CEtLQe5WllMF5fA5xM9PBlJ51UBRohXYYya8mEsJLVg?utm_source%3Dsec_alert%26utm_medium%3Demail_notification%26force_all%3Dtrue>\r\nYou can also see security activity at\r\nhttps://myaccount.google.com/notifications\r\nYou received this email to let you know about important changes to your\r\nGoogle Account and services.\r\n© 2026 Google LLC, 1600 Amphitheatre Parkway, Mountain View, CA 94043, USA\r\n','AUTOMATED_MESSAGE',NULL,'low','The sender, testfsl551@gmail.com, is claiming to be a test email and is warning the recipient about potential unauthorized access to their Google Account data. The sender is requesting the recipient to check their account activity and secure their account immediately. The recipient is expected to click on the provided links to review and manage their account settings and security.');
/*!40000 ALTER TABLE `email_batches` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `email_integrations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `email_integrations` (
  `id` int NOT NULL AUTO_INCREMENT,
  `provider` varchar(20) NOT NULL,
  `email_address` varchar(255) NOT NULL,
  `access_token` text,
  `refresh_token` text,
  `token_expiry` datetime DEFAULT NULL,
  `is_active` tinyint(1) DEFAULT '1',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `batch_prefix` varchar(10) DEFAULT NULL,
  `mailbox_type` varchar(10) DEFAULT 'PROD',
  `processing_mode` varchar(20) DEFAULT 'conversation',
  `allowed_extensions` varchar(100) DEFAULT 'pdf,doc,docx,tiff,tif',
  `max_file_size_mb` int DEFAULT '25',
  `auto_reply_no_attachment` tinyint(1) DEFAULT '1',
  `auto_reply_invalid_domain` tinyint(1) DEFAULT '1',
  `success_folder_label` varchar(100) DEFAULT 'Processed/Success',
  `failed_folder_label` varchar(100) DEFAULT 'Processed/Failed',
  `storage_provider` varchar(20) DEFAULT 'local',
  `callback_webhook_url` text,
  `callback_auth_header` text,
  `callback_enabled` tinyint(1) DEFAULT '0',
  `retention_days` int DEFAULT '90',
  `owner_user_id` int DEFAULT NULL,
  `success_auto_reply_enabled` tinyint(1) DEFAULT '0',
  `failure_auto_reply_enabled` tinyint(1) DEFAULT '0',
  `last_sync_at` datetime DEFAULT NULL,
  `last_email_processed_at` datetime DEFAULT NULL,
  `health_status` varchar(20) DEFAULT 'unknown',
  `health_message` text,
  `conversation_analysis_enabled` tinyint(1) NOT NULL DEFAULT '1',
  `auto_reply_enabled` tinyint(1) NOT NULL DEFAULT '1',
  `outlook_subscription_id` varchar(255) DEFAULT NULL,
  `outlook_subscription_expires_at` datetime DEFAULT NULL,
  `allowed_sender_domains` text,
  `auto_reply_allowed_categories` varchar(200) DEFAULT NULL,
  `auto_reply_denied_categories` varchar(200) DEFAULT NULL,
  `sla_thresholds` json DEFAULT NULL,
  `reply_signature_html` text,
  `gmail_history_id` varchar(40) DEFAULT NULL,
  `gmail_watch_expires_at` datetime DEFAULT NULL,
  `imap_host` varchar(255) DEFAULT NULL,
  `imap_port` int DEFAULT NULL,
  `imap_username` varchar(255) DEFAULT NULL,
  `imap_password` text,
  `smtp_host` varchar(255) DEFAULT NULL,
  `smtp_port` int DEFAULT NULL,
  `smtp_username` varchar(255) DEFAULT NULL,
  `smtp_password` text,
  `process_since` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `email_address` (`email_address`),
  KEY `ix_email_integrations_owner_user_id` (`owner_user_id`),
  CONSTRAINT `email_integrations_ibfk_1` FOREIGN KEY (`owner_user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `email_integrations` WRITE;
/*!40000 ALTER TABLE `email_integrations` DISABLE KEYS */;
INSERT INTO `email_integrations` VALUES (2,'gmail','testfsl551@gmail.com','gAAAAABqwKmlIX0kPh06O-SBlZoI-y3BLDa_tZ7nOpateyNmC6t28fNnKCn_qEynoLBZeG_G9UXC5xrdRwZIJgSCZ8atkmmlQKRIDR8LGBzPpzdDwlJGnfMq-Gka7AUHHPsBND47WE63SmLneVqqy-DDi0RXuLEGBsfZErTCM-TnK9K4cJkkaKk0unmmZ2qxD4pkgachbpllDBk_4UIqxu_F_9x_xb9YieiENzF-_Y-cInBvh0ZfcWXmfvVNgKwog941yMCisMWlgpqQym7yI7sxVOi8CX30u7ITNFSE-nZu7vdR95gxjTtkxbaCLCWsIVtgOgM_b3eP2SiLqq_zWoM4VkUreETjt8r8f4fPMzSyXjqPtZyM2crf6KYg8TjZedc2PLzdnCcwXpWxYfnkfFDNP6JWb88kXw==','gAAAAABqwKmlAEghNOKg_MhPnnbbDXXXzcgd5-51DpwTPNIJfV9HTsJ5JMEX5LyAsfqeN_DL5jLbSV0vqrUBIQVjsVPXz8EwXtzCPiDOomVEZj8t94xTQzYmqljm9fEGCDSnfFtV4L6xtzCuceWcOhwv_i3ITmfZZ2kCFOWVLPts1ZB-K0kAI4TKONqgCSV_kLN-5_RmD6WrAEkQq2dUj8gMdyAERQn8DQ==','2026-10-03 08:07:16',1,'2026-10-03 12:37:17','2026-10-03 12:48:20','TEST','PROD','conversation','pdf,doc,docx,tiff,tif',25,1,1,'Processed/Success','Processed/Failed','local',NULL,NULL,0,90,2,0,0,'2026-10-03 07:18:21','2026-10-03 07:08:10','healthy','Queued 0 message(s)',1,1,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'186426',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-03 07:07:17');
/*!40000 ALTER TABLE `email_integrations` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `email_replies`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `email_replies` (
  `id` int NOT NULL AUTO_INCREMENT,
  `email_id` int NOT NULL,
  `subject` text,
  `body` text NOT NULL,
  `attachments_json` json DEFAULT NULL,
  `is_draft` tinyint(1) DEFAULT NULL,
  `sent_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `requires_review` tinyint(1) NOT NULL DEFAULT '0',
  `review_reason` text,
  PRIMARY KEY (`id`),
  KEY `email_id` (`email_id`),
  CONSTRAINT `email_replies_ibfk_1` FOREIGN KEY (`email_id`) REFERENCES `emails` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `email_replies` WRITE;
/*!40000 ALTER TABLE `email_replies` DISABLE KEYS */;
/*!40000 ALTER TABLE `email_replies` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `email_response_tracker`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `email_response_tracker` (
  `id` int NOT NULL AUTO_INCREMENT,
  `email_id` int NOT NULL,
  `reply_id` int DEFAULT NULL,
  `responded_by_user_id` int DEFAULT NULL,
  `status` varchar(20) DEFAULT NULL,
  `first_response_minutes` int DEFAULT NULL,
  `escalated_to` varchar(100) DEFAULT NULL,
  `sla_breach` tinyint(1) DEFAULT NULL,
  `notes` text,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_email_response_tracker_email_id` (`email_id`),
  KEY `reply_id` (`reply_id`),
  KEY `ix_email_response_tracker_status` (`status`),
  CONSTRAINT `email_response_tracker_ibfk_1` FOREIGN KEY (`email_id`) REFERENCES `emails` (`id`) ON DELETE CASCADE,
  CONSTRAINT `email_response_tracker_ibfk_2` FOREIGN KEY (`reply_id`) REFERENCES `email_replies` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `email_response_tracker` WRITE;
/*!40000 ALTER TABLE `email_response_tracker` DISABLE KEYS */;
/*!40000 ALTER TABLE `email_response_tracker` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `email_template_versions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `email_template_versions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `template_id` int NOT NULL,
  `template_key` varchar(60) NOT NULL,
  `subject_template` text NOT NULL,
  `html_body_template` text NOT NULL,
  `signature_html` text,
  `logo_url` text,
  `created_by_user_id` int DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `created_by_user_id` (`created_by_user_id`),
  KEY `ix_email_template_versions_template_id` (`template_id`),
  CONSTRAINT `email_template_versions_ibfk_1` FOREIGN KEY (`template_id`) REFERENCES `email_templates` (`id`) ON DELETE CASCADE,
  CONSTRAINT `email_template_versions_ibfk_2` FOREIGN KEY (`created_by_user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `email_template_versions` WRITE;
/*!40000 ALTER TABLE `email_template_versions` DISABLE KEYS */;
/*!40000 ALTER TABLE `email_template_versions` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `email_templates`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `email_templates` (
  `id` int NOT NULL AUTO_INCREMENT,
  `integration_id` int DEFAULT NULL,
  `template_key` varchar(60) NOT NULL,
  `locale` varchar(10) DEFAULT 'en',
  `subject_template` text NOT NULL,
  `html_body_template` text NOT NULL,
  `is_active` tinyint(1) DEFAULT '1',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `signature_html` text,
  `logo_url` text,
  PRIMARY KEY (`id`),
  KEY `ix_email_templates_integration_id` (`integration_id`),
  KEY `ix_email_templates_key` (`template_key`),
  CONSTRAINT `email_templates_ibfk_1` FOREIGN KEY (`integration_id`) REFERENCES `email_integrations` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `email_templates` WRITE;
/*!40000 ALTER TABLE `email_templates` DISABLE KEYS */;
INSERT INTO `email_templates` VALUES (1,NULL,'domain_rejected','en','Re: $subject — Email domain not valid','<p>Hello,</p><p>Thank you for your email. Your email domain (<strong>$domain</strong>) is not valid for this mailbox, so your email has not been processed.</p><p>If you believe this is an error, please contact us from a registered email address.</p><p><em>This is an automated response — please do not reply to this message.</em></p>',1,'2026-10-03 12:02:47','2026-10-03 12:02:47',NULL,NULL),(2,NULL,'acknowledgement','en','Re: $subject — We have received your email','<p>Greetings,</p><p>Thank you for your email. We have received it and will review it and send you the status shortly.</p><p>Reference number: <strong>$batch_no</strong></p><p><em>This is an automated response — please do not reply to this message.</em></p>',1,'2026-10-03 12:02:47','2026-10-03 12:02:47',NULL,NULL),(3,NULL,'no_attachment','en','Re: $subject — No attachment found','<p>Hello,</p><p>Your email does not have any attachment to proceed further. Please upload the documents (accepted formats: $allowed_extensions) and send them again so we can process them.</p><p>Reference number: <strong>$batch_no</strong></p><p><em>This is an automated response — please do not reply to this message.</em></p>',1,'2026-10-03 12:02:47','2026-10-03 12:02:47',NULL,NULL),(4,NULL,'invalid_file_type','en','Re: $subject — Unsupported attachment(s)','<p>Hello,</p><p>Your email could not be processed because the following attachment(s) are not supported:</p>$file_list_html<p>Accepted formats: <strong>$allowed_extensions</strong> (up to $max_file_size_mb MB per file). Please send all documents again in an accepted format.</p><p>Reference number: <strong>$batch_no</strong></p><p><em>This is an automated response — please do not reply to this message.</em></p>',1,'2026-10-03 12:02:47','2026-10-03 12:02:47',NULL,NULL),(5,NULL,'invalid_attachments','en','Re: $subject — Attachment(s) could not be opened','<p>Hello,</p><p>The following attachment(s) are not valid — they are password-protected, encrypted or cannot be read:</p>$file_list_html<p>Please review them and send the documents again (without a password) so we can process them.</p><p>Reference number: <strong>$batch_no</strong></p><p><em>This is an automated response — please do not reply to this message.</em></p>',1,'2026-10-03 12:02:47','2026-10-03 12:02:47',NULL,NULL),(6,NULL,'success','en','Re: $subject — Processed successfully','<p>Hello,</p><p>Your email has been processed successfully. Below are the attachments as you shared:</p>$file_list_html<p>Reference number: <strong>$batch_no</strong></p><p><em>This is an automated response — please do not reply to this message.</em></p>',1,'2026-10-03 12:02:47','2026-10-03 12:02:47',NULL,NULL);
/*!40000 ALTER TABLE `email_templates` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `emails`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `emails` (
  `id` int NOT NULL AUTO_INCREMENT,
  `message_id` varchar(512) NOT NULL,
  `integration_id` int DEFAULT NULL,
  `subject` text NOT NULL,
  `sender_name` varchar(255) DEFAULT NULL,
  `sender_email` varchar(255) NOT NULL,
  `recipient_email` varchar(255) DEFAULT NULL,
  `body_plain` text,
  `body_html` text,
  `body_clean` text,
  `received_at` datetime NOT NULL,
  `processed_at` datetime DEFAULT NULL,
  `is_read` tinyint(1) DEFAULT NULL,
  `is_archived` tinyint(1) DEFAULT NULL,
  `thread_id` varchar(512) DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `provider_message_id` varchar(255) DEFAULT NULL,
  `sender_auth_failed` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_emails_integration_message` (`integration_id`,`message_id`),
  KEY `ix_emails_integration_received_at` (`integration_id`,`received_at`),
  KEY `ix_emails_received_at` (`received_at`),
  KEY `ix_emails_thread_id` (`thread_id`),
  KEY `ix_emails_is_read` (`is_read`),
  KEY `ix_emails_message_id` (`message_id`),
  CONSTRAINT `emails_ibfk_1` FOREIGN KEY (`integration_id`) REFERENCES `email_integrations` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `emails` WRITE;
/*!40000 ALTER TABLE `emails` DISABLE KEYS */;
/*!40000 ALTER TABLE `emails` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `failed_jobs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `failed_jobs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `job_name` varchar(100) NOT NULL,
  `args_json` json DEFAULT NULL,
  `job_key` varchar(255) DEFAULT NULL,
  `attempts` int NOT NULL DEFAULT '0',
  `error` text,
  `status` varchar(20) NOT NULL DEFAULT 'failed',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `resolved_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_failed_jobs_status` (`status`),
  KEY `ix_failed_jobs_job_name` (`job_name`),
  KEY `ix_failed_jobs_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `failed_jobs` WRITE;
/*!40000 ALTER TABLE `failed_jobs` DISABLE KEYS */;
/*!40000 ALTER TABLE `failed_jobs` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `notification_reads`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `notification_reads` (
  `notification_id` int NOT NULL,
  `user_id` int NOT NULL,
  `read_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`notification_id`,`user_id`),
  KEY `user_id` (`user_id`),
  CONSTRAINT `notification_reads_ibfk_1` FOREIGN KEY (`notification_id`) REFERENCES `notifications` (`id`) ON DELETE CASCADE,
  CONSTRAINT `notification_reads_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `notification_reads` WRITE;
/*!40000 ALTER TABLE `notification_reads` DISABLE KEYS */;
/*!40000 ALTER TABLE `notification_reads` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `notifications`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `notifications` (
  `id` int NOT NULL AUTO_INCREMENT,
  `email_id` int DEFAULT NULL,
  `type` varchar(50) NOT NULL,
  `title` varchar(255) NOT NULL,
  `message` text,
  `is_read` tinyint(1) DEFAULT '0',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `user_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `email_id` (`email_id`),
  KEY `ix_notifications_created_read` (`created_at`,`is_read`),
  KEY `ix_notifications_user_id` (`user_id`),
  CONSTRAINT `fk_notifications_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `notifications_ibfk_1` FOREIGN KEY (`email_id`) REFERENCES `emails` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `notifications` WRITE;
/*!40000 ALTER TABLE `notifications` DISABLE KEYS */;
/*!40000 ALTER TABLE `notifications` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `oauth_states`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `oauth_states` (
  `id` int NOT NULL AUTO_INCREMENT,
  `state_hash` varchar(64) NOT NULL,
  `user_id` int NOT NULL,
  `provider` varchar(20) NOT NULL,
  `expires_at` datetime NOT NULL,
  `used_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `state_hash` (`state_hash`),
  KEY `ix_oauth_states_state_hash` (`state_hash`),
  KEY `ix_oauth_states_user_id` (`user_id`),
  KEY `ix_oauth_states_expires_at` (`expires_at`),
  CONSTRAINT `oauth_states_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `oauth_states` WRITE;
/*!40000 ALTER TABLE `oauth_states` DISABLE KEYS */;
INSERT INTO `oauth_states` VALUES (1,'451db7ecda58c7ec7368daac6b0912e3933dbdf2e6520ae0ca2d6038c1bdb643',1,'gmail','2026-10-03 07:14:02',NULL,'2026-10-03 12:34:02'),(2,'8ffa4afb2671b7a3e86c500d2537d77286f8a28a86158266c746a576800e38cb',1,'gmail','2026-10-03 07:17:00','2026-10-03 07:07:15','2026-10-03 12:36:59');
/*!40000 ALTER TABLE `oauth_states` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `priority_options`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `priority_options` (
  `id` smallint NOT NULL AUTO_INCREMENT,
  `value` varchar(20) NOT NULL,
  `label` varchar(50) NOT NULL,
  `color` varchar(30) DEFAULT NULL,
  `score` smallint DEFAULT NULL,
  `sort_order` smallint DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `value` (`value`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `priority_options` WRITE;
/*!40000 ALTER TABLE `priority_options` DISABLE KEYS */;
/*!40000 ALTER TABLE `priority_options` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `sentiment_options`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sentiment_options` (
  `id` smallint NOT NULL AUTO_INCREMENT,
  `value` varchar(20) NOT NULL,
  `label` varchar(50) NOT NULL,
  `color` varchar(30) DEFAULT NULL,
  `sort_order` smallint DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `value` (`value`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `sentiment_options` WRITE;
/*!40000 ALTER TABLE `sentiment_options` DISABLE KEYS */;
/*!40000 ALTER TABLE `sentiment_options` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `user_sessions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_sessions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `refresh_token` varchar(512) NOT NULL,
  `ip_address` varchar(45) DEFAULT NULL,
  `user_agent` varchar(512) DEFAULT NULL,
  `is_active` tinyint(1) DEFAULT NULL,
  `expires_at` datetime NOT NULL,
  `last_used_at` datetime DEFAULT NULL,
  `revoked_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `refresh_token` (`refresh_token`),
  KEY `ix_user_sessions_user_id` (`user_id`),
  KEY `ix_user_sessions_refresh_token` (`refresh_token`),
  CONSTRAINT `user_sessions_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `user_sessions` WRITE;
/*!40000 ALTER TABLE `user_sessions` DISABLE KEYS */;
INSERT INTO `user_sessions` VALUES (1,1,'9df536e34f2a899fdc15f59427c1c3c600df92673549df4edbad4db9b853abea','127.0.0.1','curl/8.22.0',1,'2026-10-10 06:32:48','2026-10-03 06:32:48',NULL,'2026-10-03 12:02:48'),(2,1,'70f282485c19f86a0447121081bf5ff2c655c7c921e9acb593fcaad8419ef286','127.0.0.1','curl/8.22.0',1,'2026-10-10 06:39:16','2026-10-03 06:39:16',NULL,'2026-10-03 12:09:16'),(3,1,'aa5b63cf78dccaa5743de5e4031e1ce8ff1e541ece174c820cfb7118d65e8b58','127.0.0.1','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0',1,'2026-10-10 07:03:38','2026-10-03 07:03:38',NULL,'2026-10-03 12:33:37'),(4,1,'4666a5d0fd86d2082f5be13e0f181b1f143f63ae8399f8cad1a92b35515d1330','127.0.0.1','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0',0,'2026-10-10 07:06:00','2026-10-03 07:06:00','2026-10-03 07:06:51','2026-10-03 12:36:00'),(5,1,'b8edb6dca21b4f034a779d762b9c3a103968d368a6a5645508ca0c91e3b44e23','127.0.0.1','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0',1,'2026-10-10 07:06:56','2026-10-03 07:06:56',NULL,'2026-10-03 12:36:56');
/*!40000 ALTER TABLE `user_sessions` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `email` varchar(255) NOT NULL,
  `username` varchar(100) NOT NULL,
  `full_name` varchar(255) DEFAULT NULL,
  `hashed_password` varchar(255) NOT NULL,
  `role` varchar(20) NOT NULL DEFAULT 'client',
  `is_active` tinyint(1) DEFAULT '1',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `last_login_at` datetime DEFAULT NULL,
  `failed_login_count` int DEFAULT '0',
  `locked_until` datetime DEFAULT NULL,
  `mfa_enabled` tinyint(1) NOT NULL DEFAULT '0',
  `mfa_secret` text,
  `mfa_recovery_codes` json DEFAULT NULL,
  `mfa_last_used_step` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_users_email` (`email`),
  UNIQUE KEY `ix_users_username` (`username`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES (1,'admin@mailai.local','admin','Administrator','$2b$12$R3trtqcHt0kcA5qZJSXFIuZ5TL3d.G340B53sTaIPnQSNGW/lluva','admin',1,'2026-10-03 12:02:08','2026-10-03 12:36:56','2026-10-03 07:06:56',0,NULL,0,NULL,NULL,NULL),(2,'demo_client@client.com','demo_client','Demo Client','$2b$12$yomMKwcTbzG.31DCSANWau50QATblr9sHaLxcLOlNMgeMvb6NIqly','client',1,'2026-10-03 12:09:05','2026-10-03 12:09:05',NULL,0,NULL,0,NULL,NULL,NULL);
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

