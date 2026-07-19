from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.schemas.automation import AutomationCommand


@dataclass(frozen=True, slots=True)
class CommandAcceptance:
    provider: str
    accepted: bool
    status_code: int


class AutomationProvider(ABC):
    @abstractmethod
    async def send_command(
        self,
        command: AutomationCommand,
    ) -> CommandAcceptance:
        """Send a command and report transport-level acceptance only."""

    @abstractmethod
    async def check_availability(self) -> bool:
        """Check whether the provider can currently accept requests."""
