from __future__ import annotations

from typing import Optional, Tuple

from ..lib.storage import storage
from ..lib.output import info
from .curses_menu import EditMenu, SelectMenu
from ..lib.menu.list_manager import ListManager
from .menu_item import MenuItem, MenuItemGroup
from .types import Alignment, FrameProperties, Orientation, ResultType

class ZFSMenu:
    def __init__(self, minimal: bool = False):
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
                result = EditMenu(
                    'Enter ZFS pool name: ',
                    default=storage.get('zfs_pool_name', 'rpool'),
                    allow_skip=True
                ).input()
                
                if result.type_ == ResultType.Selection and result.text():
                    storage['zfs_pool_name'] = result.text()
            
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
                result = EditMenu(
                    'Enter ZFS boot environment name: ',
                    default=storage.get('zfs_boot_environment', 'default'),
                    allow_skip=True
                ).input()
                
                if result.type_ == ResultType.Selection and result.text():
                    storage['zfs_boot_environment'] = result.text()
            
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
                    password=True,
                    allow_skip=True
                ).input()
                
                if result.type_ == ResultType.Selection and result.text():
                    password = result.text()
                    confirm_result = EditMenu(
                        'Confirm password: ',
                        password=True,
                        allow_skip=True
                    ).input()
                    
                    if confirm_result.type_ == ResultType.Selection and confirm_result.text() == password:
                        storage['zfs_encryption_password'] = password
                    else:
                        info('Passwords do not match, please try again')
            
            elif selected_option == 'Save and Return' or selected_option is None:
                break 