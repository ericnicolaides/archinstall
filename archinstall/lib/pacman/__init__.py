import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, List

from ..exceptions import RequirementError
from ..general import SysCommand
from ..output import error, info, warn
from ..plugins import plugins
from .config import Config

if TYPE_CHECKING:
	from archinstall.lib.translationhandler import DeferredTranslation

	_: Callable[[str], DeferredTranslation]


class Pacman:

	def __init__(self, target: Path, silent: bool = False):
		self.synced = False
		self.silent = silent
		self.target = target
		self.max_retries = 3
		self.retry_delay = 5
		self.batch_size = 5  # Install packages in batches of 5

	@staticmethod
	def run(args: str, default_cmd: str = 'pacman') -> SysCommand:
		"""
		A centralized function to call `pacman` from.
		It also protects us from colliding with other running pacman sessions (if used locally).
		The grace period is set to 10 minutes before exiting hard if another pacman instance is running.
		"""
		pacman_db_lock = Path('/var/lib/pacman/db.lck')

		if pacman_db_lock.exists():
			warn(str(_('Pacman is already running, waiting maximum 10 minutes for it to terminate.')))

		started = time.time()
		while pacman_db_lock.exists():
			time.sleep(0.25)

			if time.time() - started > (60 * 10):
				error(str(_('Pre-existing pacman lock never exited. Please clean up any existing pacman sessions before using archinstall.')))
				exit(1)

		# Try up to 3 times with increasing delays
		max_retries = 3
		retry_delay = 2
		
		for attempt in range(max_retries):
			try:
				return SysCommand(f'{default_cmd} {args}')
			except Exception as e:
				if attempt < max_retries - 1:
					warn(f"Package operation failed (attempt {attempt + 1}/{max_retries}): {e}")
					warn(f"Retrying in {retry_delay} seconds...")
					time.sleep(retry_delay)
					retry_delay *= 2  # Exponential backoff
					
					# Try refreshing the package database before retrying
					if 'failed to synchronize' in str(e).lower() or 'failed retrieving file' in str(e).lower():
						try:
							SysCommand('pacman -Syy')
						except Exception as sync_err:
							warn(f"Failed to refresh package database: {sync_err}")
				else:
					raise

	def ask(self, error_message: str, bail_message: str, func: Callable, *args, **kwargs) -> None:  # type: ignore[type-arg]
		while True:
			try:
				func(*args, **kwargs)
				break
			except Exception as err:
				error(f'{error_message}: {err}')
				if not self.silent and input('Would you like to re-try this download? (Y/n): ').lower().strip() in 'y':
					continue
				raise RequirementError(f'{bail_message}: {err}')

	def sync(self) -> None:
		if self.synced:
			return
		self.ask(
			'Could not sync a new package database',
			'Could not sync mirrors',
			self.run,
			'-Syy',
			default_cmd='pacman'
		)
		self.synced = True

	def _install_package_batch(self, packages: List[str]) -> None:
		"""Install a batch of packages with retries"""
		for attempt in range(self.max_retries):
			try:
				info(f'Installing package batch: {packages}')
				self.ask(
					'Could not install packages',
					'Package installation failed',
					SysCommand,
					f'pacstrap -C /etc/pacman.conf -K {self.target} {" ".join(packages)} --noconfirm',
					peek_output=True
				)
				return
			except Exception as e:
				if attempt < self.max_retries - 1:
					warn(f"Failed to install package batch (attempt {attempt + 1}/{self.max_retries}): {e}")
					warn(f"Retrying in {self.retry_delay} seconds...")
					time.sleep(self.retry_delay)
					self.retry_delay *= 2  # Exponential backoff
					
					# Try refreshing the package database before retrying
					try:
						self.sync()
					except Exception as sync_err:
						warn(f"Failed to refresh package database: {sync_err}")
				else:
					raise

	def strap(self, packages: str | list[str]) -> None:
		"""
		Install packages using pacstrap, with improved error handling and batch processing
		"""
		self.sync()
		if isinstance(packages, str):
			packages = [packages]

		for plugin in plugins.values():
			if hasattr(plugin, 'on_pacstrap'):
				if (result := plugin.on_pacstrap(packages)):
					packages = result

		info(f'Installing packages in batches of {self.batch_size}: {packages}')

		# Process packages in batches
		for i in range(0, len(packages), self.batch_size):
			batch = packages[i:i + self.batch_size]
			self._install_package_batch(batch)


__all__ = [
	'Config',
	'Pacman',
]
