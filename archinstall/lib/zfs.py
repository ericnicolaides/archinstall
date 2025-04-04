from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any
import time
import shutil

from .output import debug, info, error, warn
from .exceptions import DiskError
from .general import SysCommand, SysCallError, SysCommandWorker
from .storage import storage

class ZFSManager:
    """
    Standalone ZFS management for Archinstall.
    This class handles ZFS-specific operations without deeply integrating
    with the filesystem framework to avoid circular imports.
    """
    
    def __init__(self):
        # Get configuration from storage or use defaults
        raw_pool_name = storage.get('zfs_pool_name')
        self._pool_name = raw_pool_name if raw_pool_name else "ROOT"
        self._compression = storage.get('zfs_compression', "lz4")
        self._boot_environment = storage.get('zfs_boot_environment', "default")
        self._enable_encryption = storage.get('zfs_encryption', False)
        self._encryption_password = storage.get('zfs_encryption_password', '')
        
        # Log configuration for debugging
        info(f"ZFS Manager initialized with:")
        info(f"- Pool name: {self._pool_name} (from storage: {raw_pool_name})")
        info(f"- Boot environment: {self._boot_environment}")
        info(f"- Compression: {self._compression}")
        info(f"- Encryption enabled: {self._enable_encryption}")
        
    def create_pool(self, devices: list[str], ashift: int = 12) -> bool:
        """Create a ZFS pool with the specified devices"""
        try:
            cmd = ["zpool", "create", 
                "-o", f"ashift={ashift}",
                "-o", "feature@encryption=enabled",
                "-o", f"compression={self._compression}",
                "-o", "atime=off",
                "-o", "relatime=on",
                "-o", "xattr=sa",
                "-o", "mountpoint=none",
                self._pool_name]
                
            cmd.extend(devices)
            
            debug(f"Creating ZFS pool with command: {' '.join(cmd)}")
            result = SysCommand(cmd)
            if result.exit_code != 0:
                error(f"ZFS pool creation failed: {result}")
                return False
            
            info(f"ZFS pool {self._pool_name} created successfully")
            return True
        except Exception as e:
            error(f"Error creating ZFS pool: {e}")
            return False

    def create_datasets(self) -> bool:
        """Create basic ZFS datasets structure"""
        try:
            # Log the pool name being used
            info(f"ZFS: Creating datasets using pool name: {self._pool_name}")
            
            # Create root dataset structure
            info(f"ZFS: Creating base ROOT dataset structure")
            SysCommand(["zfs", "create", "-o", "mountpoint=none", f"{self._pool_name}/ROOT"])
            
            # Create the boot environment
            info(f"ZFS: Creating boot environment dataset: {self._pool_name}/ROOT/{self._boot_environment}")
            SysCommand(["zfs", "create",
                "-o", "mountpoint=/",
                "-o", "canmount=noauto",
                "-o", f"compression={self._compression}",
                f"{self._pool_name}/ROOT/{self._boot_environment}"])
            
            # Create other datasets one by one with EXPLICIT error handling for each
            # This ensures one failing dataset doesn't prevent others from being created
            datasets = [
                ["/home", f"{self._pool_name}/home"],
                ["/var", f"{self._pool_name}/var"],
                ["/var/lib", f"{self._pool_name}/var/lib"],
                ["/var/log", f"{self._pool_name}/var/log"],
                ["/var/cache", f"{self._pool_name}/var/cache"],
                ["/var/cache/pacman", f"{self._pool_name}/var/cache/pacman"],
                ["/var/cache/pacman/pkg", f"{self._pool_name}/var/cache/pacman/pkg"],
                ["/tmp", f"{self._pool_name}/tmp"]
            ]
            
            for mountpoint, dataset in datasets:
                try:
                    info(f"ZFS: Creating dataset {dataset} with mountpoint {mountpoint}")
                    SysCommand(["zfs", "create", "-o", f"mountpoint={mountpoint}", dataset])
                    info(f"ZFS: Successfully created dataset {dataset}")
                except Exception as e:
                    error(f"ZFS: Error creating dataset {dataset}: {e}")
                    # Continue to create other datasets even if one fails
            
            info("ZFS: All datasets creation attempts completed")
            return True
        except Exception as e:
            error(f"ZFS: Major error in dataset creation process: {e}")
            return False

    def setup_encryption(self) -> bool:
        """Configure ZFS native encryption if enabled"""
        if not self._enable_encryption or not self._encryption_password:
            debug("ZFS encryption is disabled or no password provided, skipping")
            return True
            
        try:
            from .general import SysCommandWorker
            
            # Create a new encrypted dataset
            cmd = ["zfs", "create",
                "-o", "encryption=aes-256-gcm",
                "-o", "keyformat=passphrase",
                "-o", "keylocation=prompt",
                "-o", "mountpoint=/encrypted",
                f"{self._pool_name}/encrypted"]
                
            # Use SysCommandWorker to handle passphrase input
            worker = SysCommandWorker(cmd)
            worker.write(f"{self._encryption_password}\n")
            worker.write(f"{self._encryption_password}\n")  # Confirm passphrase
            worker.execute()
            
            info("ZFS encryption configured successfully")
            return True
        except Exception as e:
            error(f"Error setting up ZFS encryption: {e}")
            return False

    def create_swap(self, size: int = 4) -> bool:
        """Create a ZFS volume for swap"""
        try:
            # Create swap dataset
            SysCommand(["zfs", "create",
                "-o", "compression=zle",
                "-o", "logbias=throughput",
                "-o", "sync=always",
                "-o", "primarycache=metadata", 
                "-o", "secondarycache=none",
                "-o", "com.sun:auto-snapshot=false",
                f"{self._pool_name}/swap"])
            
            # Create swap volume (size in GB)
            SysCommand(["zfs", "create",
                "-V", f"{size}G",
                "-b", "4K",
                f"{self._pool_name}/swap/swapfile"])
            
            # Format as swap
            SysCommand(["mkswap", f"/dev/zvol/{self._pool_name}/swap/swapfile"])
            
            info("ZFS swap volume created successfully")
            return True
        except Exception as e:
            error(f"Error creating ZFS swap: {e}")
            return False

    def mount_datasets(self, target: Path) -> bool:
        """Mount ZFS datasets to the target installation path"""
        try:
            # Export pool to avoid mount conflicts
            SysCommand(["zpool", "export", self._pool_name])
            
            # Import pool with alternate root
            SysCommand(["zpool", "import", "-R", str(target), self._pool_name])
            
            # Mount the root dataset
            SysCommand(["zfs", "mount", f"{self._pool_name}/ROOT/{self._boot_environment}"])
            
            # Mount other datasets
            SysCommand(["zfs", "mount", "-a"])
            
            info("ZFS datasets mounted successfully")
            return True
        except Exception as e:
            error(f"Error mounting ZFS datasets: {e}")
            return False

    def configure_boot(self, target: Path) -> bool:
        """Configure the system for booting from ZFS"""
        try:
            # Set bootfs property
            SysCommand(["zpool", "set", f"bootfs={self._pool_name}/ROOT/{self._boot_environment}", self._pool_name])
            
            # Create and populate ZFS cache file
            cache_dir = target / "etc/zfs"
            cache_dir.mkdir(parents=True, exist_ok=True)
            
            SysCommand(["zpool", "set", "cachefile=/etc/zfs/zpool.cache", self._pool_name])
            
            # Enable necessary ZFS services
            systemd_services = [
                "zfs.target",
                "zfs-import-cache",
                "zfs-mount",
                "zfs-import.target"
            ]
            
            for service in systemd_services:
                SysCommand(["systemctl", "--root", str(target), "enable", service])
            
            info("ZFS boot configuration completed")
            return True
        except Exception as e:
            error(f"Error configuring ZFS boot: {e}")
            return False

    def setup_zfs_system(self, target_devices: list[str], target_mount: Path) -> bool:
        """
        Complete ZFS setup process from start to finish
        
        Args:
            target_devices: List of device paths to create ZFS pool on
            target_mount: Path where the new system will be mounted
            
        Returns:
            True if successful, False otherwise
        """
        steps = [
            (self.create_pool, [target_devices]),
            (self.create_datasets, []),
            (self.setup_encryption, []),
            (self.create_swap, []),
            (self.mount_datasets, [target_mount]),
            (self.configure_boot, [target_mount]),
        ]
        
        for step_func, step_args in steps:
            if not step_func(*step_args):
                error(f"ZFS setup failed during {step_func.__name__}")
                return False
        
        info("ZFS system setup completed successfully")
        return True

# Create a global instance for easy import
zfs_manager = ZFSManager() 