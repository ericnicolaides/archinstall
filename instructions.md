# Instructions for Implementing ZFS Support in Archinstall

## Overview
These instructions outline a simplified approach to adding ZFS support to Archinstall by creating a dedicated ZFS module that integrates with the existing system through strategic hooks rather than deeply integrating with the filesystem framework.

## Step 2: Create a Dedicated ZFS Module

Create a new file at `archinstall/lib/zfs.py` that will contain all ZFS-specific functionality:

```python
from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any

from .output import debug, info, error
from .exceptions import DiskError
from .installer.utils import SysCommand, SysCallError
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
            from .installer.utils import SysCommandWorker
            
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
            SysCommand(["arch-chroot", str(target), "pacman", "-S", "--noconfirm", 
                        "zfs-dkms", "zfs-utils", "linux-headers"])
            
            # Configure mkinitcpio hooks for ZFS
            with open(f"{target}/etc/mkinitcpio.conf", "r") as f:
                content = f.read()
                
            # Add ZFS hooks
            if "zfs" not in content:
                content = content.replace(
                    "HOOKS=(",
                    "HOOKS=(base udev autodetect modconf block keyboard zfs filesystems)")
                
                with open(f"{target}/etc/mkinitcpio.conf", "w") as f:
                    f.write(content)
                    
            # Rebuild initramfs
            SysCommand(["arch-chroot", str(target), "mkinitcpio", "-P"])
            
            return True
        except Exception as e:
            error(f"Error installing ZFS packages: {e}")
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
```

## Step 3: Modify FilesystemType Enum to Add ZFS

Edit `archinstall/lib/models/device_model.py` to add ZFS to the FilesystemType enum:

```python
class FilesystemType(Enum):
    # Existing filesystems...
    Ext4 = 'ext4'
    Ext3 = 'ext3'
    Ext2 = 'ext2'
    Btrfs = 'btrfs'
    # Add ZFS
    ZFS = 'zfs'
    # ... other existing filesystem types
```

## Step 4: Add Hooks in the Installer

Add hooks in `archinstall/lib/installer.py` to detect and handle ZFS configurations:

```python
# Add this import at the top
from .zfs import zfs_manager

# Add this method to the Installer class
def _has_zfs_config(self) -> bool:
    """Check if ZFS configuration is present in storage"""
    return 'zfs_pool_name' in storage

# Add ZFS handling to perform_installation method
def perform_installation(self, mountpoint: Path) -> bool:
    """
    Performs the installation steps on a block device.
    Only requirement is that the block devices exist.
    """
    
    # If ZFS is configured, handle it separately
    if self._has_zfs_config():
        info("ZFS configuration detected, using ZFS installation path")
        
        # Get device paths from disk config
        devices = []
        for mod in self._disk_config.device_modifications:
            for part_mod in mod.partitions:
                if part_mod.dev_path:
                    devices.append(str(part_mod.dev_path))
        
        # Handle ZFS setup
        if not zfs_manager.setup_zfs_system(devices, self.target):
            error("ZFS setup failed")
            return False
        
        # Continue with the rest of the installation
        # No need to format or mount partitions as ZFS manager handled it
    else:
        # Existing non-ZFS installation path
        # ... (original code for formatting and mounting)
        pass
        
    # Continue with package installation and system configuration
    # ... (rest of the installation process remains unchanged)
```

## Step 5: Add ZFS UI Options in the TUI

Modify `archinstall/tui/disk_menu.py` to add ZFS options to the filesystem selection:

```python
# Add ZFS option to the filesystem type selection
def _ask_fs_type(self, current_fs_type: Optional[FilesystemType] = None) -> FilesystemType:
    fs_options = [
        (FilesystemType.Ext4, str(_('ext4'))),
        (FilesystemType.Ext3, str(_('ext3'))),
        (FilesystemType.Ext2, str(_('ext2'))),
        (FilesystemType.Btrfs, str(_('btrfs'))),
        (FilesystemType.ZFS, str(_('zfs'))),  # Add ZFS option
        (FilesystemType.XFS, str(_('xfs'))),
        (FilesystemType.F2FS, str(_('f2fs'))),
        (FilesystemType.Fat32, str(_('fat32'))),
        (FilesystemType.Fat16, str(_('fat16'))),
        (FilesystemType.Fat12, str(_('fat12'))),
        (FilesystemType.Ntfs, str(_('ntfs'))),
        (FilesystemType.LinuxSwap, str(_('swap'))),
    ]
    
    # Rest of the function remains unchanged
```

## Step 6: Add ZFS Configuration Menu

Create a new file at `archinstall/tui/zfs_menu.py` for ZFS-specific configuration:

```python
from __future__ import annotations

from typing import Optional

from ..lib.menu import Menu
from ..lib.storage import storage
from ..lib.output import info
from ..lib.menu.list_manager import ListManager
from ..lib.menu.textinput import TextInput
from ..lib.menu.verifytick import VerifyTick

class ZFSMenu(Menu):
    def __init__(self, minimal: bool = False):
        super().__init__()
        self.minimal = minimal
        
    def show(self) -> None:
        """
        Show the ZFS configuration menu
        """
        if not storage.get('zfs_pool_name', None):
            # Initialize with defaults if not set
            storage['zfs_pool_name'] = 'rpool'
            storage['zfs_compression'] = 'lz4'
            storage['zfs_boot_environment'] = 'default'
            storage['zfs_encryption'] = False
            storage['zfs_encryption_password'] = ''
        
        while True:
            options = [
                ('Pool Name', storage.get('zfs_pool_name', 'rpool')),
                ('Compression', storage.get('zfs_compression', 'lz4')),
                ('Boot Environment', storage.get('zfs_boot_environment', 'default')),
                ('Enable Encryption', 'Yes' if storage.get('zfs_encryption', False) else 'No'),
            ]
            
            if storage.get('zfs_encryption', False):
                options.append(('Encryption Password', '********' if storage.get('zfs_encryption_password', '') else 'Not Set'))
            
            if not self.minimal:
                options.append(('Save and Return', 'Save configuration and return to previous menu'))
            
            selected_option, index = ListManager(
                options,
                'ZFS Configuration Options'
            ).run()
            
            if selected_option == 'Pool Name':
                new_value = TextInput('Enter ZFS pool name').run()
                if new_value:
                    storage['zfs_pool_name'] = new_value
            
            elif selected_option == 'Compression':
                compression_options = [
                    ('lz4', 'LZ4 (default, balanced)'),
                    ('zstd', 'ZSTD (better compression, more CPU)'),
                    ('gzip', 'GZIP (high compression, high CPU)'),
                    ('off', 'No compression')
                ]
                selected_comp, _ = ListManager(
                    compression_options,
                    'Select ZFS Compression Algorithm'
                ).run()
                if selected_comp:
                    storage['zfs_compression'] = selected_comp
            
            elif selected_option == 'Boot Environment':
                new_value = TextInput('Enter ZFS boot environment name').run()
                if new_value:
                    storage['zfs_boot_environment'] = new_value
            
            elif selected_option == 'Enable Encryption':
                result = VerifyTick(
                    'Enable ZFS native encryption?',
                    default=storage.get('zfs_encryption', False)
                ).run()
                storage['zfs_encryption'] = result
            
            elif selected_option == 'Encryption Password' and storage.get('zfs_encryption', False):
                new_value = TextInput('Enter ZFS encryption password', password=True).run()
                if new_value:
                    confirm = TextInput('Confirm password', password=True).run()
                    if new_value == confirm:
                        storage['zfs_encryption_password'] = new_value
                    else:
                        info('Passwords do not match, please try again')
            
            elif selected_option == 'Save and Return' or selected_option is None:
                break
```

## Step 7: Integrate ZFS Menu with Disk Menu

Modify `archinstall/tui/disk_menu.py` to show the ZFS configuration menu when ZFS is selected:

```python
from .zfs_menu import ZFSMenu

# Inside the partition edit method or where filesystem is selected
def _on_fs_type_selected(self, fs_type: FilesystemType):
    # Set the filesystem type
    self.partition.fs_type = fs_type
    
    # If ZFS is selected, show ZFS configuration menu
    if fs_type == FilesystemType.ZFS:
        ZFSMenu().show()
    
    # Continue with existing code...
```

## Step 8: Modify Device Handler to Skip Traditional Formatting for ZFS

Modify `archinstall/lib/disk/device_handler.py` to skip traditional formatting for ZFS:

```python
def format(self, fs_type: FilesystemType, path: Path) -> None:
    # Add this at the top of the method
    if fs_type == FilesystemType.ZFS:
        debug('ZFS filesystem type detected - skipping traditional format')
        return
        
    # Continue with existing format logic for other filesystems
```

## Step 9: Add ZFS Package Dependencies

Modify `archinstall/lib/installer.py` to ensure ZFS packages are installed when needed:

```python
def _install_essential_packages(self) -> None:
    """
    Install essential packages
    """
    # Existing code
    
    # Add ZFS packages if needed
    if self._has_zfs_config():
        packages.extend(['zfs-dkms', 'zfs-utils', 'linux-headers'])
    
    # Continue with existing package installation
```

## Step 10: Testing Your Implementation

1. After making these changes, build and test the code:
```bash
python -m archinstall
```

2. Test the ZFS implementation by:
   - Selecting disk partitioning
   - Creating a partition with ZFS filesystem
   - Configuring ZFS options
   - Completing the installation

3. Verify the installation boots properly and ZFS pools are correctly set up.

## Troubleshooting Tips

1. If you encounter import errors:
   - Check the import statements to ensure there are no circular dependencies
   - Move imports inside functions where necessary
   - Consider using lazy imports for problematic modules

2. For ZFS-specific issues:
   - Ensure ZFS packages are installed in the live environment
   - Check for proper kernel module loading
   - Verify all necessary ZFS commands are available

3. For bootloader issues:
   - Make sure GRUB is configured properly for ZFS
   - Check if ZFS kernel parameters are correctly set
   - Verify boot environment is properly configured

This approach avoids deep integration with the existing filesystem framework, keeping ZFS support as a parallel path in the installer that's triggered when ZFS is selected. This should avoid most of the circular import and complexity issues you've encountered. 