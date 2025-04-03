"""Arch Linux installer - guided, templates etc."""

import importlib
import os
import sys
import time
import traceback
from typing import TYPE_CHECKING
from pathlib import Path

# Add import for SysCallError (needed if version check is restored, safe otherwise)
from .lib.general import SysCallError
from archinstall.lib.args import arch_config_handler
from archinstall.lib.disk.utils import disk_layouts

from .lib.hardware import SysInfo
from .lib.output import FormattedOutput, debug, error, info, log, warn
from .lib.pacman import Pacman
from .lib.plugins import load_plugin, plugins
from .lib.translationhandler import DeferredTranslation, Language, translation_handler
from .tui.curses_menu import Tui

if TYPE_CHECKING:
	from collections.abc import Callable

	_: Callable[[str], DeferredTranslation]


# add the custom _ as a builtin, it can now be used anywhere in the
# project to mark strings as translatable with _('translate me')
DeferredTranslation.install()

# Log various information about hardware before starting the installation. This might assist in troubleshooting
debug(f"Hardware model detected: {SysInfo.sys_vendor()} {SysInfo.product_name()}; UEFI mode: {SysInfo.has_uefi()}")
debug(f"Processor model detected: {SysInfo.cpu_model()}")
debug(f"Memory statistics: {SysInfo.mem_available()} available out of {SysInfo.mem_total()} total installed")
debug(f"Virtualization detected: {SysInfo.virtualization()}; is VM: {SysInfo.is_vm()}")
debug(f"Graphics devices detected: {SysInfo._graphics_devices().keys()}")

# For support reasons, we'll log the disk layout pre installation to match against post-installation layout
debug(f"Disk states before installing:\n{disk_layouts()}")


if 'sphinx' not in sys.modules and 'pylint' not in sys.modules:
	if '--help' in sys.argv or '-h' in sys.argv:
		arch_config_handler.print_help()
		exit(0)
	if os.getuid() != 0:
		print(_("Archinstall requires root privileges to run. See --help for more."))
		exit(1)


# @archinstall.plugin decorator hook to programmatically add
# plugins in runtime. Useful in profiles_bck and other things.
def plugin(f, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
	plugins[f.__name__] = f


def _fetch_arch_db() -> None:
	info("Fetching Arch Linux package database...")
	try:
		Pacman.run("-Sy")
	except Exception as e:
		debug(f'Failed to sync Arch Linux package database: {e}')
		exit(1)


# NOTE: _check_new_version function was removed as per user request


def main() -> None:
	"""
	This can either be run as the compiled and installed application: python setup.py install
	OR straight as a module: python -m archinstall
	In any case we will be attempting to load the provided script to be run from the scripts/ folder
	"""
	if not arch_config_handler.args.offline:
		_fetch_arch_db() # Keep the initial db sync

	# REMOVED version check call
	# if not arch_config_handler.args.skip_version_check:
	# 		_check_new_version()

	script = arch_config_handler.args.script

	mod_name = f'archinstall.scripts.{script}'
	# by loading the module we'll automatically run the script
	importlib.import_module(mod_name)


def run_as_a_module() -> None:
	exc = None

	try:
		main()
	except Exception as e:
		exc = e
	finally:
		# restore the terminal to the original state
		Tui.shutdown()

		if exc:
			err = ''.join(traceback.format_exception(exc))
			error(err)

			text = (
				'Archinstall experienced the above error. If you think this is a bug, please report it to\n'
				'https://github.com/archlinux/archinstall and include the log file "/var/log/archinstall/install.log".\n\n'
				'Hint: To extract the log from a live ISO \ncurl -F\'file=@/var/log/archinstall/install.log\' https://0x0.st\n'
			)

			warn(text)
			exit(1)


__all__ = [
	'DeferredTranslation',
	'FormattedOutput',
	'Language',
	'Pacman',
	'SysInfo',
	'Tui',
	'arch_config_handler',
	'debug',
	'disk_layouts',
	'error',
	'info',
	'load_plugin',
	'log',
	'plugin',
	'translation_handler',
	'warn',
	'run_as_a_module', # Ensure this is exported
	'main'
]

# Ensure the script can be run directly using `python -m archinstall`
if __name__ == '__main__':
	run_as_a_module() 