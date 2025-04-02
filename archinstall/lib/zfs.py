from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any
import time

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
        self._pool_name = storage.get('zfs_pool_name', "rpool")
        self._compression = storage.get('zfs_compression', "lz4")
        self._boot_environment = storage.get('zfs_boot_environment', "default")
        self._enable_encryption = storage.get('zfs_encryption', False)
        self._encryption_password = storage.get('zfs_encryption_password', '')
        
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
            # Create root dataset structure
            SysCommand(["zfs", "create", "-o", "mountpoint=none", f"{self._pool_name}/ROOT"])
            
            # Create the boot environment
            SysCommand(["zfs", "create",
                "-o", "mountpoint=/",
                "-o", "canmount=noauto",
                "-o", f"compression={self._compression}",
                f"{self._pool_name}/ROOT/{self._boot_environment}"])
            
            # Create other common datasets
            common_datasets = [
                ["zfs", "create", "-o", "mountpoint=/home", f"{self._pool_name}/home"],
                ["zfs", "create", "-o", "mountpoint=/var", f"{self._pool_name}/var"],
                ["zfs", "create", "-o", "mountpoint=/var/lib", f"{self._pool_name}/var/lib"],
                ["zfs", "create", "-o", "mountpoint=/var/log", f"{self._pool_name}/var/log"],
            ]
            
            for cmd in common_datasets:
                SysCommand(cmd)
                
            info("ZFS datasets created successfully")
            return True
        except Exception as e:
            error(f"Error creating ZFS datasets: {e}")
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

    def install_zfs_packages(self, target: Path) -> bool:
        """Install ZFS packages in the target system"""
        try:
            # First try installing linux-headers as it's a prerequisite
            try:
                info("Installing linux-headers...")
                SysCommand(["arch-chroot", str(target), "pacman", "-S", "--noconfirm", "linux-headers"])
            except Exception as e:
                warn(f"Failed to install linux-headers: {e}")
                # Continue anyway as headers might already be installed
            
            # Then try installing ZFS packages
            try:
                info("Installing ZFS packages...")
                SysCommand(["arch-chroot", str(target), "pacman", "-S", "--noconfirm", "zfs-dkms", "zfs-utils"])
            except Exception as e:
                warn(f"Failed to install ZFS packages from official repos, trying archzfs repo...")
                
                # Add archzfs repo if not present
                with open(f"{target}/etc/pacman.conf", "r") as f:
                    content = f.read()
                    
                if "[archzfs]" not in content:
                    with open(f"{target}/etc/pacman.conf", "a") as f:
                        f.write("\n[archzfs]\n")
                        f.write("Server = https://archzfs.com/$repo/$arch\n")
                
                # Import and sign the archzfs key
                try:
                    SysCommand(["arch-chroot", str(target), "pacman-key", "-r", "F75D9D76"])
                    SysCommand(["arch-chroot", str(target), "pacman-key", "--lsign-key", "F75D9D76"])
                except Exception as key_error:
                    warn(f"Could not import archzfs key: {key_error}")
                
                # Update repos
                info("Updating package database...")
                try:
                    SysCommand(["arch-chroot", str(target), "pacman", "-Syy"])
                except Exception as e:
                    warn(f"Failed to update package database: {e}")
                
                # Install packages one by one with retries
                packages = ["zfs-dkms", "zfs-utils"]
                max_retries = 3
                retry_delay = 5
                
                for pkg in packages:
                    for attempt in range(max_retries):
                        try:
                            info(f"Installing {pkg} (attempt {attempt + 1}/{max_retries})...")
                            SysCommand(["arch-chroot", str(target), "pacman", "-S", "--noconfirm", pkg])
                            break
                        except Exception as pkg_error:
                            if attempt < max_retries - 1:
                                warn(f"Failed to install {pkg}: {pkg_error}")
                                warn(f"Retrying in {retry_delay} seconds...")
                                time.sleep(retry_delay)
                                retry_delay *= 2  # Exponential backoff
                            else:
                                error(f"Failed to install {pkg} after {max_retries} attempts")
                                return False
            
            # Configure mkinitcpio hooks for ZFS
            info("Configuring mkinitcpio hooks...")
            with open(f"{target}/etc/mkinitcpio.conf", "r") as f:
                content = f.read()
                
            # Add ZFS hooks if not present
            if "zfs" not in content:
                content = content.replace(
                    "HOOKS=(",
                    "HOOKS=(base udev autodetect modconf block keyboard zfs filesystems)")
                
                with open(f"{target}/etc/mkinitcpio.conf", "w") as f:
                    f.write(content)
            
            # Rebuild initramfs with retries
            info("Rebuilding initramfs...")
            max_retries = 3
            retry_delay = 5
            
            for attempt in range(max_retries):
                try:
                    SysCommand(["arch-chroot", str(target), "mkinitcpio", "-P"])
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        warn(f"Failed to rebuild initramfs: {e}")
                        warn(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        error(f"Failed to rebuild initramfs after {max_retries} attempts")
                        return False
            
            return True
            
        except Exception as e:
            error(f"Error during ZFS package installation: {e}")
            return False

    def configure_bootloader(self, target: Path) -> bool:
        """Configure GRUB for ZFS booting"""
        try:
            # Install GRUB with ZFS support
            SysCommand(["arch-chroot", str(target), "pacman", "-S", "--noconfirm", "grub"])
            
            # Configure GRUB for ZFS
            grub_default_path = f"{target}/etc/default/grub"
            with open(grub_default_path, "r") as f:
                content = f.read()
                
            # Add ZFS-specific kernel parameters
            if "zfs=" not in content:
                content = content.replace(
                    'GRUB_CMDLINE_LINUX=""',
                    f'GRUB_CMDLINE_LINUX="root=ZFS={self._pool_name}/ROOT/{self._boot_environment} zfs_force=1"')
                
                with open(grub_default_path, "w") as f:
                    f.write(content)
            
            # Install GRUB
            SysCommand(["arch-chroot", str(target), "grub-install", "--target=x86_64-efi", 
                        "--efi-directory=/boot", "--bootloader-id=GRUB"])
            
            # Generate GRUB configuration
            SysCommand(["arch-chroot", str(target), "grub-mkconfig", "-o", "/boot/grub/grub.cfg"])
            
            return True
        except Exception as e:
            error(f"Error configuring bootloader for ZFS: {e}")
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
            (self.install_zfs_packages, [target_mount]),
            (self.configure_bootloader, [target_mount])
        ]
        
        for step_func, step_args in steps:
            if not step_func(*step_args):
                error(f"ZFS setup failed during {step_func.__name__}")
                return False
        
        info("ZFS system setup completed successfully")
        return True

# Create a global instance for easy import
zfs_manager = ZFSManager() 