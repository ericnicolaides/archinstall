class RequirementError(Exception):
	pass


class DiskError(Exception):
	pass


class UnknownFilesystemFormat(Exception):
	pass


class SysCallError(Exception):
	def __init__(self, message: str, exit_code: int | None = None, worker_log: bytes = b'') -> None:
		super().__init__(message)
		self.message = message
		self.exit_code = exit_code
		self.worker_log = worker_log
		self.worker = None  # Add worker attribute to prevent AttributeError when it's accessed
		self.session = None  # Add session attribute to prevent AttributeError when it's accessed


class HardwareIncompatibilityError(Exception):
	pass


class ServiceException(Exception):
	pass


class PackageError(Exception):
	pass


class Deprecated(Exception):
	pass


class DownloadTimeout(Exception):
	'''
	Download timeout exception raised by DownloadTimer.
	'''
