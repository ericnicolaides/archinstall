from __future__ import annotations

from typing import Optional, Tuple

from ..lib.storage import storage
from ..lib.output import info
from .curses_menu import EditMenu, SelectMenu
from ..lib.menu.list_manager import ListManager
from .menu_item import MenuItem, MenuItemGroup
from .types import Alignment, FrameProperties, Orientation, ResultType
from ..lib.disk.device_handler import device_handler
from ..lib.models.device_model import DeviceModification

class ZFSMenu:
    def __init__(self, minimal: bool = False, is_guided: bool = False):
        self.minimal = minimal
        self.is_guided = is_guided
        
    def show(self) -> None:
        """
        Show the ZFS configuration menu
        """
        if not storage.get('zfs_pool_name', None):
            # Initialize with defaults if not set
            storage['zfs_pool_name'] = 'ROOT'
            storage['zfs_compression'] = 'lz4'
            storage['zfs_boot_environment'] = 'default'
            storage['zfs_encryption'] = False
            storage['zfs_encryption_password'] = ''
            storage['zfs_boot_strategy'] = 'zfs_boot'  # Default to ZFS boot
        
        # First prompt for boot strategy if not already chosen
        if not storage.get('zfs_boot_strategy_selected', False):
            self._prompt_boot_strategy()
        
        while True:
            options = [
                ('Pool Name', storage.get('zfs_pool_name', 'ROOT')),
                ('Compression', storage.get('zfs_compression', 'lz4')),
                ('ZFS System Root Dataset Name', storage.get('zfs_boot_environment', 'default')),
                ('Boot Strategy', 'ZFS Boot' if storage.get('zfs_boot_strategy', 'zfs_boot') == 'zfs_boot' else 'Separate Boot Partition'),
                ('Enable Encryption', 'Yes' if storage.get('zfs_encryption', False) else 'No'),
            ]
            
            if storage.get('zfs_encryption', False):
                options.append(('Encryption Password', '********' if storage.get('zfs_encryption_password', '') else 'Not Set'))
            
            if not self.minimal:
                options.append(('Save and Return', 'Save configuration and return to previous menu'))
            
            # Instead of using ListManager which doesn't work well for this simple menu,
            # let's use SelectMenu directly which should be more appropriate
            menu_items = [MenuItem(option[0], value=option) for option in options]
            group = MenuItemGroup(menu_items, sort_items=False)
            
            result = SelectMenu(
                group,
                header='ZFS Configuration Options',
                alignment=Alignment.CENTER,
                allow_skip=False
            ).run()
            
            if result.type_ != ResultType.Selection:
                break
                
            selected_item = result.get_value()
            selected_option = selected_item[0]
            
            if selected_option == 'Pool Name':
                result = EditMenu(
                    'Enter ZFS pool name: ',
                    default_text=storage.get('zfs_pool_name', 'ROOT'),
                    allow_skip=True
                ).input()
                
                if result.type_ == ResultType.Selection and result.text():
                    old_value = storage.get('zfs_pool_name')
                    storage['zfs_pool_name'] = result.text()
                    info(f"ZFS pool name changed from '{old_value}' to '{result.text()}'")
            
            elif selected_option == 'Compression':
                # Create a simple menu for compression options
                comp_items = [
                    MenuItem('LZ4 (default, balanced)', value='lz4'),
                    MenuItem('ZSTD (better compression, more CPU)', value='zstd'),
                    MenuItem('GZIP (high compression, high CPU)', value='gzip'),
                    MenuItem('No compression', value='off')
                ]
                comp_group = MenuItemGroup(comp_items, sort_items=False)
                
                comp_result = SelectMenu(
                    comp_group,
                    header='Select ZFS Compression Algorithm',
                    alignment=Alignment.CENTER,
                    allow_skip=False
                ).run()
                
                if comp_result.type_ == ResultType.Selection:
                    storage['zfs_compression'] = comp_result.get_value()
            
            elif selected_option == 'ZFS System Root Dataset Name':
                result = EditMenu(
                    'Enter ZFS System Root Dataset Name (this configures where your system will boot from): ',
                    default_text=storage.get('zfs_boot_environment', 'default'),
                    allow_skip=True
                ).input()
                
                if result.type_ == ResultType.Selection and result.text():
                    storage['zfs_boot_environment'] = result.text()
            
            elif selected_option == 'Boot Strategy':
                self._prompt_boot_strategy()
            
            elif selected_option == 'Enable Encryption':
                # Create yes/no menu for encryption
                group = MenuItemGroup.yes_no()
                if storage.get('zfs_encryption', False):
                    group.set_selected_by_value(MenuItem.yes().value)
                else:
                    group.set_selected_by_value(MenuItem.no().value)
                    
                result = SelectMenu(
                    group,
                    header='Enable ZFS native encryption?',
                    alignment=Alignment.CENTER,
                    orientation=Orientation.HORIZONTAL,
                    columns=2,
                    allow_skip=False
                ).run()
                
                storage['zfs_encryption'] = result.item() == MenuItem.yes()
            
            elif selected_option == 'Encryption Password' and storage.get('zfs_encryption', False):
                result = EditMenu(
                    'Enter ZFS encryption password: ',
                    hide_input=True,
                    allow_skip=True
                ).input()
                
                if result.type_ == ResultType.Selection and result.text():
                    password = result.text()
                    confirm_result = EditMenu(
                        'Confirm password: ',
                        hide_input=True,
                        allow_skip=True
                    ).input()
                    
                    if confirm_result.type_ == ResultType.Selection and confirm_result.text() == password:
                        storage['zfs_encryption_password'] = password
                    else:
                        info('Passwords do not match, please try again')
            
            elif selected_option == 'Save and Return':
                break
    
    def _prompt_boot_strategy(self):
        """Ask user for ZFS boot strategy"""
        # For guided partitioning, we always start clean
        if self.is_guided:
            # Clear any existing partitions since this is guided mode
            storage.setdefault('device_modifications', [])
            storage['device_modifications'] = []
            for device in device_handler._devices.values():
                # Create a new device modification that wipes the device
                device_mod = DeviceModification(device=device, wipe=True)
                storage['device_modifications'].append(device_mod)
            
            # Show boot strategy selection directly
            boot_items = [
                MenuItem('Use ZFS for everything (except ESP)', value='zfs_boot'),
                MenuItem('Use separate non-ZFS boot partition (ext4)', value='separate_boot')
            ]
            boot_group = MenuItemGroup(boot_items, sort_items=False)
            
            # Set selected based on previous selection if any
            if storage.get('zfs_boot_strategy', 'zfs_boot') == 'separate_boot':
                boot_group.set_selected_by_value('separate_boot')
            else:
                boot_group.set_selected_by_value('zfs_boot')
            
            boot_result = SelectMenu(
                boot_group,
                header='Select ZFS Boot Strategy',
                alignment=Alignment.CENTER,
                allow_skip=False
            ).run()
            
            if boot_result.type_ == ResultType.Selection:
                storage['zfs_boot_strategy'] = boot_result.get_value()
                storage['zfs_boot_strategy_selected'] = True
            return
            
        # For manual partitioning, check for existing partitions
        has_existing_partitions = False
        has_existing_boot = False
        
        for device in device_handler._devices.values():
            if device.partition_infos:
                has_existing_partitions = True
                for part in device.partition_infos:
                    if part.mountpoints and '/boot' in [str(mp) for mp in part.mountpoints]:
                        has_existing_boot = True
                        break
        
        # If we have existing partitions in manual mode, show appropriate warning/options
        if has_existing_partitions:
            warning_items = [
                MenuItem('Keep existing partitions (recommended)', value='keep'),
                MenuItem('Delete all partitions and start over', value='delete')
            ]
            warning_group = MenuItemGroup(warning_items, sort_items=False)
            
            warning_text = "Warning: Existing partitions detected!\n\n"
            if has_existing_boot:
                warning_text += "An existing boot partition was found.\n"
                warning_text += "- Keep: Will use existing boot partition\n"
            warning_text += "- Delete: Will remove ALL existing partitions\n"
            warning_text += "\nWhat would you like to do?"
            
            warning_result = SelectMenu(
                warning_group,
                header=warning_text,
                alignment=Alignment.CENTER,
                allow_skip=False
            ).run()
            
            if warning_result.type_ == ResultType.Selection:
                if warning_result.get_value() == 'delete':
                    # Clear all existing partitions
                    storage.setdefault('device_modifications', [])
                    storage['device_modifications'] = []
                    for device in device_handler._devices.values():
                        # Create a new device modification that wipes the device
                        device_mod = DeviceModification(device=device, wipe=True)
                        storage['device_modifications'].append(device_mod)
                    has_existing_boot = False
                elif has_existing_boot:
                    # If keeping existing boot, force separate boot strategy
                    storage['zfs_boot_strategy'] = 'separate_boot'
                    storage['zfs_boot_strategy_selected'] = True
                    info('Using existing boot partition')
                    return
        
        # Only show boot strategy selection if we're not using existing boot
        boot_items = [
            MenuItem('Use ZFS for everything (except ESP)', value='zfs_boot'),
            MenuItem('Use separate non-ZFS boot partition (ext4)', value='separate_boot')
        ]
        boot_group = MenuItemGroup(boot_items, sort_items=False)
        
        # Set selected based on previous selection if any
        if storage.get('zfs_boot_strategy', 'zfs_boot') == 'separate_boot':
            boot_group.set_selected_by_value('separate_boot')
        else:
            boot_group.set_selected_by_value('zfs_boot')
        
        boot_result = SelectMenu(
            boot_group,
            header='Select ZFS Boot Strategy',
            alignment=Alignment.CENTER,
            allow_skip=False
        ).run()
        
        if boot_result.type_ == ResultType.Selection:
            storage['zfs_boot_strategy'] = boot_result.get_value()
            storage['zfs_boot_strategy_selected'] = True 