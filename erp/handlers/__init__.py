"""Tornado request handlers: the web screens, the REST API and the WebSocket.

Module overview:

``base``    common base class: sessions, roles, languages, rendering, forms
``setup``   first run installation wizard
``auth``    login, logout, "My account", language switch
``menus``   main menu, administration and backup menus, in-app help
``data``    record lists, forms, views, live monitor, CSV import/export
``files``   download and streaming of uploaded files
``admin``   administration: data definitions, menus, users, API keys,
            settings, backup/restore, audit log, system information
``api``     REST API (``/api/v1``) and WebSocket stream for other systems

Handlers never talk to the database directly from the event loop: they pass a
function to ``self.db(...)``, which runs it in a worker thread inside one
transaction (see :meth:`erp.db.Database.run`).  Such functions are usually
small nested ``def load(conn): ...`` closures.
"""
