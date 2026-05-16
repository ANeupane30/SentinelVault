-- SQL Server Script to create Users table
-- Run this script in SQL Server Management Studio (SSMS) on your SentinelVaultDb database

IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Users' and xtype='U')
BEGIN
	CREATE TABLE [dbo].[Users]
	(
		[Id] UNIQUEIDENTIFIER NOT NULL PRIMARY KEY,
		[Email] NVARCHAR(255) NOT NULL UNIQUE,
		[PasswordHash] NVARCHAR(MAX) NOT NULL,
		[FirstName] NVARCHAR(100) NOT NULL,
		[LastName] NVARCHAR(100) NOT NULL,
		[CreatedAt] DATETIME2 NOT NULL DEFAULT GETUTCDATE(),
		[LastLogin] DATETIME2 NULL,
		[IsActive] BIT NOT NULL DEFAULT 1
	);

	-- Create indexes for common queries
	CREATE NONCLUSTERED INDEX [IX_Users_Email] 
		ON [dbo].[Users] ([Email]);

	CREATE NONCLUSTERED INDEX [IX_Users_IsActive] 
		ON [dbo].[Users] ([IsActive]);

	PRINT 'Users table created successfully.';
END
ELSE
BEGIN
	PRINT 'Users table already exists.';
END
GO

-- Verify the table structure
SELECT * FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'Users';
GO
