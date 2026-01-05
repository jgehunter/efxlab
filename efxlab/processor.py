"""
Event processor - orchestrates event handling with deterministic ordering.
"""

from typing import List

import structlog

from efxlab.events import (
    BaseEvent,
    ClientTradeEvent,
    ClockTickEvent,
    ConfigUpdateEvent,
    EventType,
    HedgeFillEvent,
    HedgeOrderEvent,
    MarketUpdateEvent,
)
from efxlab.handlers import (
    OutputRecord,
    handle_client_trade,
    handle_clock_tick,
    handle_config_update,
    handle_hedge_fill,
    handle_hedge_order,
    handle_market_update,
)
from efxlab.state import EngineState

logger = structlog.get_logger()


class EventProcessor:
    """
    Deterministic event processor.

    Processes events in strict order, maintaining state transitions.
    """

    def __init__(self, initial_state: EngineState | None = None):
        self.state = initial_state or EngineState()
        self.output_records: List[OutputRecord] = []

    def process_event(self, event: BaseEvent) -> None:
        """
        Process a single event through appropriate handler.

        Args:
            event: Event to process

        Raises:
            ValueError: If event type is unknown
        """
        try:
            # Dispatch to appropriate handler
            if isinstance(event, ClientTradeEvent):
                new_state, outputs = handle_client_trade(self.state, event)
            elif isinstance(event, MarketUpdateEvent):
                new_state, outputs = handle_market_update(self.state, event)
            elif isinstance(event, ConfigUpdateEvent):
                new_state, outputs = handle_config_update(self.state, event)
            elif isinstance(event, HedgeOrderEvent):
                new_state, outputs = handle_hedge_order(self.state, event)
            elif isinstance(event, HedgeFillEvent):
                new_state, outputs = handle_hedge_fill(self.state, event)
            elif isinstance(event, ClockTickEvent):
                new_state, outputs = handle_clock_tick(self.state, event)
            else:
                raise ValueError(f"Unknown event type: {type(event)}")

            # Update state
            self.state = new_state
            self.output_records.extend(outputs)

            # Log progress
            logger.debug(
                "event_processed",
                event_type=event.event_type.value,
                timestamp=event.timestamp.isoformat(),
                sequence_id=event.sequence_id,
            )

        except Exception as e:
            # Log error with full context
            logger.error(
                "event_processing_failed",
                event_type=event.event_type.value,
                timestamp=event.timestamp.isoformat(),
                sequence_id=event.sequence_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            # Re-raise to fail fast (can be changed to graceful degradation)
            raise

    def process_events(self, events: List[BaseEvent]) -> EngineState:
        """
        Process a list of events in order.

        Events are assumed to be already sorted. This method processes them
        sequentially and returns the final state.

        Args:
            events: List of events (must be sorted)

        Returns:
            Final engine state
        """
        logger.info("processing_started", event_count=len(events))

        for i, event in enumerate(events):
            self.process_event(event)

            # Log progress periodically
            if (i + 1) % 10000 == 0:
                logger.info(
                    "processing_progress",
                    processed=i + 1,
                    total=len(events),
                    percent=round(100 * (i + 1) / len(events), 1),
                )

        logger.info(
            "processing_completed",
            event_count=len(events),
            final_event_count=self.state.event_count,
            output_records=len(self.output_records),
        )

        return self.state

    def get_output_records(self) -> List[OutputRecord]:
        """Get all output records generated during processing."""
        return self.output_records

    def get_state(self) -> EngineState:
        """Get current state."""
        return self.state
