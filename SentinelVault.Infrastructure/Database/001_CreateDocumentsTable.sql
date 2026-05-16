-- SQL Server Script to create Documents table
-- Run this script in SQL Server Management Studio (SSMS) on your SentinelVaultDb database

IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Documents' and xtype='U')
BEGIN
	CREATE TABLE [dbo].[Documents]
	(
		[Id] UNIQUEIDENTIFIER NOT NULL PRIMARY KEY,
		[FileName] NVARCHAR(255) NOT NULL,
		[FilePath] NVARCHAR(512) NOT NULL,
		[UserId] UNIQUEIDENTIFIER NOT NULL,
		[CreatedDate] DATETIME2 NOT NULL DEFAULT GETUTCDATE(),
		[UploadedAt] DATETIME2 NOT NULL,
		[Status] INT NOT NULL DEFAULT 0, -- 0=Pending, 1=Uploaded, 2=Processing, 3=Completed, 4=Failed
		[CreatedAtUtc] DATETIME2 NOT NULL DEFAULT GETUTCDATE()
	);

	-- Create indexes for common queries
	CREATE NONCLUSTERED INDEX [IX_Documents_UserId] 
		ON [dbo].[Documents] ([UserId]);

	CREATE NONCLUSTERED INDEX [IX_Documents_Status] 
		ON [dbo].[Documents] ([Status]);

	CREATE NONCLUSTERED INDEX [IX_Documents_CreatedDate] 
		ON [dbo].[Documents] ([CreatedDate]);

	PRINT 'Documents table created successfully.';
END
ELSE
BEGIN
	PRINT 'Documents table already exists.';
END
GO

-- Verify the table structure
SELECT * FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'Documents';
GO
