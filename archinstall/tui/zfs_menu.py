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