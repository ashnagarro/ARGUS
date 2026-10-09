---
doc_id: rds-sqlserver-read-replicas
url: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/SQLServer.ReadReplicas.html
retrieved_at: 2026-10-10
sha256: ecf0474b2bd9688ec95e7958f109b465cf41ba5786e8e5c8272ef909893f25a0
---

# Working with read replicas for Microsoft SQL Server in Amazon RDS

You usually use read replicas to configure replication between Amazon RDS DB instances. For general information about read replicas, see Working with DB instance read replicas.

In this section, you can find specific information about working with read replicas on Amazon RDS for SQL Server.

- Synchronizing database users and objects with a SQL Server read replica

- Troubleshooting a SQL Server read replica problem

## Configuring read replicas for SQL Server

Before a DB instance can serve as a source instance for replication, you must enable automatic backups on the source DB instance. To do so, you set the backup retention period to a value other than 0. Setting this type of deployment also enforces that automatic backups are enabled.

Creating a SQL Server read replica doesn't require an outage for the primary DB instance. Amazon RDS sets the necessary parameters and permissions for the source DB instance and the read replica without any service interruption. A snapshot is taken of the source DB instance, and this snapshot becomes the read replica. No outage occurs when you delete a read replica.

You can create up to 15 read replicas from one source DB instance. For replication to operate effectively, we recommend that you configure each read replica with the same amount of compute and storage resources as the source DB instance. If you scale the source DB instance, also scale the read replicas.

The SQL Server DB engine version of the source DB instance and all of its read replicas must be the same. Amazon RDS upgrades the primary immediately after upgrading the read replicas, regardless of the maintenance window. For more information about upgrading the DB engine version, see Upgrades of the Microsoft SQL Server DB engine.

For a read replica to receive and apply changes from the source, it should have sufficient compute and storage resources. If a read replica reaches compute, network, or storage resource capacity, the read replica stops receiving or applying changes from its source. You can modify the storage and CPU resources of a read replica independently from its source and other read replicas.

For more information about how to create a read replica, see Creating a read replica.

## Read replica limitations with SQL Server

The following limitations apply to SQL Server read replicas on Amazon RDS:

- Read replicas are only available on the SQL Server Enterprise Edition (EE) engine.

- Read replicas are available for SQL Server versions 2016–2025.

- You can create up to 15 read replicas from one source DB instance. Replication might lag when your source DB instance has more than 5 read replicas.

- Read replicas are only available for DB instances running on DB instance classes with four or more vCPUs.

- A read replica supports up to 100 databases depending on the instance class type and availability mode. You must create databases on the source DB instance to automatically replicate them to the read replicas. You can't choose individual databases to replicate. For more information, see Limitations for Microsoft SQL Server DB instances.

- You can't drop a database from a read replica. To drop a database, drop it from the source DB instance with the rds_drop_database stored procedure. For more information, see Dropping a database in an Amazon RDS for Microsoft SQL Server DB instance.

- If the source DB instance uses Transparent Data Encryption (TDE) to encrypt data, the read replica also automatically configures TDE. If the source DB instance uses a KMS key to encrypt data, read replicas in the same region use the same KMS key. For cross-region read replicas, you must specify a KMS key from the read replica’s region when creating the read replica. You can't change the KMS key for a read replica.

- Read replicas have the same time zone and collation as the source DB instance, regardless of Availabilty Zone they're created in.

- The following aren't supported on Amazon RDS for SQL Server:

- Backup retention of read replicas

- Point-in-time recovery from read replicas

- Manual snapshots of read replicas

- Multi-AZ read replicas

- Creating read replicas of read replicas

- Synchronization of user logins to read replicas

- Amazon RDS for SQL Server doesn't intervene to mitigate high replica lag between a source DB instance and its read replicas. Make sure that the source DB instance and its read replicas are sized properly, in terms of computing power and storage, to suit their operational load.

- You can replicate between the AWS GovCloud (US-East) and AWS GovCloud (US-West) Regions, but not into or out of AWS GovCloud (US) Regions.

## Option considerations for RDS for SQL Server replicas

Before you create an RDS for SQL Server replica, consider the following requirements, restrictions, and recommendations:

- If your SQL Server replica is in the same Region as its source DB instance, make sure that it belongs to the same option group as the source DB instance. Modifications to the source option group or source option group membership propagate to replicas. These changes are applied to the replicas immediately after they are applied to the source DB instance, regardless of the replica's maintenance window. For more information about option groups, see Working with option groups.

- When you create a SQL Server cross-Region replica, Amazon RDS creates a dedicated option group for it. You can't remove an SQL Server cross-Region replica from its dedicated option group. No other DB instances can use the dedicated option group for a SQL Server cross-Region replica. The following options are replicated options. To add replicated options to a SQL Server cross-Region replica, add it to the source DB instance's option group. The option is also installed on all of the source DB instance's replicas. The following options are non-replicated options. You can add or remove non-replicated options from a dedicated option group. The following options are not supported for read replicas. The following options are partially supported for cross-Region read replicas. When you promote a SQL Server cross-Region read replica, the promoted replica behaves the same as other SQL Server DB instances, including the management of its options. For more information about option groups, see Working with option groups.

- TDE

- MSDTC

- SQLSERVER_AUDIT

- To enable the SQLSERVER_AUDIT option on cross-Region read replica, add the SQLSERVER_AUDIT option on the dedicated option group on the cross-region read replica and the source instance’s option group. By adding the SQLSERVER_AUDIT option on the source instance of SQL Server cross-Region read replica, you can create Server Level Audit Object and Server Level Audit Specifications on each of the cross-Region read replicas of the source instance. To allow the cross-Region read replicas access to upload the completed audit logs to an Amazon S3 bucket, add the SQLSERVER_AUDIT option to the dedicated option group and configure the option settings. The Amazon S3 bucket that you use as a target for audit files must be in the same Region as the cross-Region read replica. You can modify the option setting of the SQLSERVER_AUDIT option for each cross region read replica independently so each can access an Amazon S3 bucket in their respective Region.

- SSRS

- SSAS

- SSIS

- SQLSERVER_BACKUP_RESTORE

- The source DB instance of a SQL Server cross-Region replica can have the SQLSERVER_BACKUP_RESTORE option, but you can not perform native restores on the source DB instance until you delete all its cross-Region replicas. Any existing native restore tasks will be cancelled during the creation of a cross-Region replica. You can't add the SQLSERVER_BACKUP_RESTORE option to a dedicated option group. For more information on native backup and restore, see Importing and exporting SQL Server databases using native backup and restore
