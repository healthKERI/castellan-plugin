# -*- encoding: utf-8 -*-
"""
castellan.schema.list module

Schema list page — shows schemas stored on the Castellan server.
"""
from typing import Any, TYPE_CHECKING

import qasync
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout
from keri import help
from keri.help import helping
from keri.core.scheming import Schemer
from locksmith.ui import colors
from locksmith.ui.toolkit.tables import PaginatedTableWidget

from ..core import remoting
from .upload import UploadSchemaDialog
from .view import ViewSchemaDialog

if TYPE_CHECKING:
    from locksmith.ui.vault.page import VaultPage

logger = help.ogler.getLogger(__name__)


class SchemaListPage(QWidget):
    """Paginated list of schemas stored on the Castellan server."""

    def __init__(self, app, parent: "VaultPage | None" = None):
        super().__init__(parent)
        self._parent = parent
        self.app = app
        self.vault_name = ""
        self._schema_cache: dict[str, dict[str, Any]] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors.BACKGROUND_CONTENT))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self.table = PaginatedTableWidget(
            columns=["Title", "Version", "Created Date"],
            column_widths={"Version": 200, "Created Date": 185, "Actions": 50},
            title="Schemas",
            icon_path=":/assets/material-icons/schema.svg",
            show_add_button=True,
            add_button_text="Upload Schema(s)",
            row_actions=["View", "Delete"],
            row_action_icons={
                "View": ":/assets/material-icons/view.svg",
                "Delete": ":/assets/material-icons/delete.svg",
            },
            row_actions_callback=self._get_row_actions,
            items_per_page=10,
            show_search=True,
            column_sort_mapping={
                "Title": "title",
                "Version": "version",
                "Created Date": "created_at",
            },
            transform_func=self._transform_schema_to_row,
            parent=self,
        )

        self.table.add_clicked.connect(self._on_upload_schemas)
        self.table.row_action_triggered.connect(self._on_row_action_signal)
        self.table.row_clicked.connect(self._on_row_clicked)
        self.table.load_requested.connect(self._on_load_requested)
        self.table.load_error.connect(self._on_load_error)

        layout.addWidget(self.table)

    def _transform_schema_to_row(self, data: dict[str, Any]) -> dict[str, Any]:
        schema = data['schema']
        said = data.get('said', '')
        title = schema.get('title', '')
        version = schema.get('version', '')
        created_at_date = helping.fromIso8601(data.get('created_at', ''))
        created_at = created_at_date.strftime("%b %d, %Y %I:%M %p")

        # Check if schema is loaded locally
        is_loaded = self.app.vault.hby.db.schema.get(keys=(said,)) is not None

        row_data = {
            'Title': title,
            'Version': version,
            'Created Date': created_at,
            '_said': said,
            '_is_loaded': is_loaded,
            '_schema': schema,  # Store full schema for loading
        }

        self._schema_cache[said] = schema
        return row_data

    @staticmethod
    def _get_row_actions(row_data: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
        """
        Get row actions based on whether the schema is loaded locally.

        Args:
            row_data: Row data dictionary

        Returns:
            Tuple of (actions list, icons dict)
        """
        all_icons = {
            "View": ":/assets/material-icons/view.svg",
            "Delete": ":/assets/material-icons/delete.svg",
            "Load Schema": ":/assets/material-icons/download.svg",
        }

        actions = ["View", "Delete"]

        # Add "Load Schema" action if schema is not loaded locally
        if not row_data.get('_is_loaded', True):
            actions.insert(1, "Load Schema")  # Insert after View

        return actions, {a: all_icons[a] for a in actions}

    @qasync.asyncSlot(dict)
    async def _on_load_requested(self, params: dict):
        if not self.app:
            self.table.load_error.emit("No app instance available")
            return

        self._schema_cache.clear()

        try:
            response = await remoting.fetch_schemas(
                app=self.app,
                page=params["page"],
                page_size=params["page_size"],
                filter_term=params.get("filter_term"),
                order=params.get("order"),
            )
            self.table.set_page_data(response, data_key="schemas")
        except Exception as e:
            logger.exception(f"Error loading schemas: {e}")
            self.table.load_error.emit(str(e))

    @staticmethod
    def _on_load_error(error_msg: str):
        logger.error(f"Table load error: {error_msg}")

    def _on_upload_schemas(self):
        if not self.app:
            return

        dialog = UploadSchemaDialog(
            app=self.app,
            on_refresh=self._refresh_table,
            parent=self,
        )
        dialog.show()

    def _refresh_table(self):
        self.table.refresh()

    def _on_row_clicked(self, row_data: Any):
        if isinstance(row_data, dict):
            self._on_row_action({str(k): v for k, v in row_data.items()}, "View")

    def _on_row_action_signal(self, row_data: object, action: str):
        if isinstance(row_data, dict):
            self._on_row_action({str(k): v for k, v in row_data.items()}, action)

    def _on_row_action(self, row_data: dict[str, Any], action: str):
        said = row_data.get('_said', '')
        if action == "View":
            self._view_schema(said)
        elif action == "Load Schema":
            self._on_load_schema(row_data)
        elif action == "Delete":
            self._on_delete_schema(row_data)

    def _view_schema(self, said: str):
        schema = self._schema_cache.get(said)
        if not schema:
            logger.error(f"Schema {said} not in cache")
            return

        dialog = ViewSchemaDialog(schema=schema, parent=self)
        dialog.show()

    def _on_load_schema(self, row_data: dict[str, Any]) -> None:
        """
        Handle Load Schema action - loads schema into local database.

        Args:
            row_data: Row data containing schema information
        """
        schema = row_data.get('_schema')
        if not schema:
            logger.error("Cannot load: no schema data found in row")
            return

        try:
            # Create Schemer object from schema data
            schemer = Schemer(sed=schema)

            # Save to local database
            self.app.vault.hby.db.schema.pin(keys=(schemer.said,), val=schemer)

            logger.info(f"Schema {schemer.said} loaded successfully into local database")

            # Refresh the table to update the row actions
            self._refresh_table()

        except Exception as e:
            logger.exception(f"Error loading schema: {e}")
            # Could show error to user if there's a notification mechanism

    def _on_delete_schema(self, row_data: dict[str, Any]) -> None:
        """Handle Delete schema action."""
        from .delete import DeleteSchemaDialog

        schema_said = row_data.get("_said", "")
        schema_title = row_data.get("Title", "")

        if not schema_said:
            logger.error("Cannot delete: no schema SAID found")
            return

        if not schema_title:
            # Fallback to SAID prefix if title is missing
            schema_title = schema_said[:12]

        logger.info(f"Opening delete dialog for schema: {schema_title}")

        dialog = DeleteSchemaDialog(
            app=self.app,
            schema_title=schema_title,
            schema_said=schema_said,
            on_success=self._on_schema_deleted,
            parent=self._parent
        )
        dialog.open()

    def _on_schema_deleted(self, schema_said: str):
        """Handle successful schema deletion."""
        logger.info(f"Schema {schema_said} deleted, reloading list")
        self.on_show()  # Refresh the schemas list

    def set_vault_name(self, vault_name: str):
        self.vault_name = vault_name

    def on_show(self):
        self._schema_cache.clear()
        self.table.request_load()
