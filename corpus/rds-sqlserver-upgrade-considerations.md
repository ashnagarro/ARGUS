---
doc_id: rds-sqlserver-upgrade-considerations
url: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_UpgradeDBInstance.SQLServer.Considerations.html
retrieved_at: 2026-10-09
sha256: 0db1918ae930cb5239b3f7ccbf924960289d3f15f9946893331ba4465de28e7f
---

# Considerations for SQL Server upgrades

Amazon RDS takes two DB snapshots during the upgrade process. The first DB snapshot is of the DB instance before any upgrade changes have been made. The second DB snapshot is taken after the upgrade finishes.

###### Note

Amazon RDS only takes DB snapshots if you have set the backup retention period for your DB instance to a number greater than 0. To change your backup retention period, see Modifying an Amazon RDS DB instance.

After an upgrade is completed, you can't revert to the previous version of the database engine. If you want to return to the previous version, restore from the DB snapshot that was taken before the upgrade to create a new DB instance.

During a minor or major version upgrade of SQL Server, the Free Storage Space and Disk Queue Depth metrics will display -1. After the upgrade is completed, both metrics will return to normal.

Before you upgrade your SQL Server instance, review the following information.

## Best practices before initiating an upgrade

Before starting the upgrade process, implement the following preparatory stpes to allow optimal upgrade performance and minimize potential issues:

- Schedule upgrades during low transaction volume periods.

- Minimize write operations during the upgrade window.

This allows Amazon RDS to complete upgrades faster by reducing the number of transaction log backup files that RDS needs to restore during secondary-to-primary pairing.

- Identify and monitor long-running transactions.

- Ensure all critical transactions are commited before starting the upgrade.

- Prevent long-running transactions during the upgrade window.

Review and optimize transaction log files:

- Shrink oversized log files.

- Reduce high log consumption patterns.

- Manage Virtual Log Files (VLFs).

- Maintain adequate free space for normal operations.

## Multi-AZ considerations

Amazon RDS supports Multi-AZ deployments for DB instances running Microsoft SQL Server by using SQL Server Database Mirroring (DBM) or Always On Availability Groups (AGs). For more information, see Multi-AZ deployments for Amazon RDS for Microsoft SQL Server.

In a Multi-AZ deployment (Mirroring/AlwaysOn), when an upgrade is requested, RDS follows a rolling upgrade strategy for the primary and secondary instances. Rolling upgrades ensure at least one instance is available for transactions while the secondary instance is upgraded. The outage is expected to only last the duration of a failover.

During the upgrade, RDS removes the secondary instance from the Multi-AZ configuration, performs an upgrade of the secondary instance, and restores any transaction log backups from the primary taken during the time it was disconnected. After all the log backups are restored, RDS joins the upgraded secondary to the primary. When all the databases are in a synchronized state, RDS performs a failover to the upgraded secondary instance. Once the failover is completed, RDS proceeds with upgrading the old primary instance, restores any transaction log backups, and pairs it with the new primary.

To minimize this failover duration, we recommend using AlwaysOn AGs availability group listener endpoint when using client libraries that support the MultiSubnetFailover connection option in the connection string. When using the availability group listener endpoint, failover times are typically less than 10 seconds, however, this duration does not include any additional crash recovery time.

## Read replica considerations

During a database version upgrade, Amazon RDS upgrades all of your read replicas along with the primary DB instance. Amazon RDS does not support database version upgrades on the read replicas separately. For more information on read replicas, see Working with read replicas for Microsoft SQL Server in Amazon RDS.

When you perform a database version upgrade of the primary DB instance, all its read-replicas are also automatically upgraded. Amazon RDS will upgrade all of the read replicas simultaneously before upgrading the primary DB instance. Read replicas may not be available until the database version upgrade on the primary DB instance is complete.

## Option group considerations

If your DB instance uses a custom DB option group, in some cases Amazon RDS can't automatically assign your DB instance a new option group. For example, when you upgrade to a new major version, you must specify a new option group. We recommend that you create a new option group, and add the same options to it as your existing custom option group.

For more information, see Creating an option group or Copying an option group.

## Parameter group considerations

If your DB instance uses a custom DB parameter group:

- Amazon RDS automatically reboots the DB instance after an upgrade.

- In some cases, RDS can't automatically assign a new parameter group to your DB instance. For example, when you upgrade to a new major version, you must specify a new parameter group. We recommend that you create a new parameter group, and configure the parameters as in your existing custom parameter group.

For more information, see Creating a DB parameter group in Amazon RDS or Copying a DB parameter group in Amazon RDS.
