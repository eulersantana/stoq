# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2005-2008 Async Open Source <http://www.async.com.br>
## All rights reserved
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU Lesser General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU Lesser General Public License for more details.
##
## You should have received a copy of the GNU Lesser General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., or visit: http://www.gnu.org/.
##
##  Author(s): Stoq Team <stoq-devel@async.com.br>
##
""" Login dialog for users authentication"""

import logging

from gi.repository import Gtk, Gdk
from kiwi.component import get_utility, provide_utility
from kiwi.ui.delegates import GladeDelegate

from stoqlib.api import api
from stoqlib.database.interfaces import ICurrentUser
from stoqlib.exceptions import DatabaseError, LoginError, UserProfileError
from stoqlib.domain.person import LoginUser
from stoqlib.gui.base.dialogs import RunnableView
from stoqlib.gui.utils.logo import render_logo_pixbuf
from stoqlib.lib.interfaces import CookieError, ICookieFile
from stoqlib.lib.message import warning
from stoqlib.lib.translation import stoqlib_gettext

_ = stoqlib_gettext

RETRY_NUMBER = 3
log = logging.getLogger(__name__)


class LoginDialog(GladeDelegate, RunnableView):
    domain = 'stoq'
    toplevel_name = gladefile = "LoginDialog"
    size = (-1, -1)

    def __init__(self, title=None):
        self.keyactions = {Gdk.KEY_Escape: self.on_escape_pressed}
        GladeDelegate.__init__(self, gladefile=self.gladefile,
                               keyactions=self.keyactions,
                               delete_handler=Gtk.main_quit)
        if title:
            self.set_title(title)
        self.get_toplevel().set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.setup_widgets()

    def setup_widgets(self):
        self.get_toplevel().set_size_request(*self.size)
        self.notification_label.set_text('')
        self.notification_label.set_color('black')

        if api.sysparam.get_bool('DISABLE_COOKIES'):
            self.remember.hide()
            self.remember.set_active(False)

        gtkimage = Gtk.Image()
        gtkimage.set_from_pixbuf(render_logo_pixbuf('login'))
        self.logo_container.add(gtkimage)
        self.logo_container.show_all()

    def force_username(self, username):
        self.username.set_text(username)
        self.username.set_sensitive(False)
        self.password.grab_focus()

    def _initialize(self, username=None, password=None):
        self.username.set_text(username or "")
        self.password.set_text(password or "")
        self.retval = None
        self.username.grab_focus()

    def on_escape_pressed(self):
        Gtk.main_quit()

    def on_delete_event(self, window, event):
        self.close()

    def on_ok_button__clicked(self, button):
        self._do_login()

    def on_quit_button__clicked(self, button):
        Gtk.main_quit()
        self.retval = False
        # oneiric didn't need this, but it is required for
        # precise for reasons unknown
        # application.py as well
        raise SystemExit

    def on_username__activate(self, entry):
        self.password.grab_focus()

    def on_password__activate(self, entry):
        self._do_login()

    def set_field_sensitivity(self, sensitive=True):
        for widget in (self.username, self.password, self.ok_button,
                       self.quit_button):
            widget.set_sensitive(sensitive)

    def _do_login(self):
        username = str(self.username.get_text().strip())
        password = str(self.password.get_text().strip())
        password = LoginUser.hash(password)
        self.retval = username, password
        self.set_field_sensitivity(False)
        self.notification_label.set_color('black')
        msg = _(" Authenticating user...")
        self.notification_label.set_text(msg)
        while Gtk.events_pending():
            Gtk.main_iteration()
        Gtk.main_quit()
        self.set_field_sensitivity(True)

    def run(self, username=None, password=None, msg=None):
        if msg:
            self.notification_label.set_color('red')
            self.notification_label.set_text(msg)
        self._initialize(username, password)
        self.show()
        Gtk.main()
        return self.retval


class LoginHelper:

    def __init__(self, username=None):
        self.user = None
        self._force_username = username

    def _check_user(self, username, pw_hash):
        username = str(username)
        pw_hash = str(pw_hash)
        # This function is really just a post-validation item.
        default_store = api.get_default_store()
        current_branch = api.get_current_branch(default_store)

        user = LoginUser.authenticate(default_store, username, pw_hash,
                                      current_branch)

        # Dont know why, but some users have this empty. Prevent user from
        # login in, since it will break later
        if not user.profile:
            msg = (_("User '%s' has no profile set, "
                     "but this should not happen.") % user.username + '\n\n' +
                   _("Please contact your system administrator or Stoq team."))
            warning(msg)
            raise LoginError(_("User does not have a profile"))

        user.login(api.get_current_station(default_store))

        # ICurrentUser might already be provided which is the case when
        # creating a new database, thus we need to replace it.
        provide_utility(ICurrentUser, user, replace=True)
        return user

    def cookie_login(self):
        if api.sysparam.get_bool('DISABLE_COOKIES'):
            log.info("Cookies disable by parameter")
            return

        cookie_file = get_utility(ICookieFile)
        try:
            username, password = cookie_file.get()
        except CookieError:
            log.info("Not using cookie based login")
            return

        def is_md5(password):
            # This breaks for passwords that are 32 characters long,
            # uses only digits and lowercase a-f, pretty unlikely as
            # real-world password
            if len(password) != 32:
                return False
            for c in '1234567890abcdef':
                password = password.replace(c, '')
            return password == ''

        # Migrate old passwords to md5 hashes.
        if not is_md5(password):
            password = LoginUser.hash(password)
            cookie_file.store(username, password)

        try:
            user = self._check_user(username, password)
        except (LoginError, UserProfileError, DatabaseError) as e:
            log.info("Cookie login failed: %r" % e)
            return

        log.info("Logging in using cookie credentials")
        return user

    def validate_user(self):
        """ Checks if an user can log in or not.
        :returns: a user object
        """
        # If there is only one user, and that user is admin with a blank
        # password, just log the user in
        store = api.get_default_store()
        if store.find(LoginUser).count() == 1:
            try:
                return self._check_user(u'admin', LoginUser.hash(u''))
            except Exception:
                pass

        log.info("Showing login dialog")
        # Loop for logins
        retry = 0
        retry_msg = None
        dialog = None

        while retry < RETRY_NUMBER:
            username = self._force_username
            password = None

            if not dialog:
                dialog = LoginDialog(_("Stoq - Access Control"))
            if self._force_username:
                dialog.force_username(username)

            ret = dialog.run(username, password, msg=retry_msg)

            # user cancelled (escaped) the login dialog
            if not ret:
                return

            # Use credentials
            if not (isinstance(ret, (tuple, list)) and len(ret) == 2):
                raise ValueError('Invalid return value, got %s'
                                 % str(ret))

            username, password = ret

            if not username:
                retry_msg = _("specify an username")
                continue

            try:
                user = self._check_user(username, password)
            except (LoginError, UserProfileError) as e:
                # We don't hide the dialog here; it's kept open so the
                # next loop we just can call run() and display the error
                cookie = get_utility(ICookieFile, None)
                if cookie:
                    cookie.clear()
                retry += 1
                retry_msg = str(e)
            except DatabaseError as e:
                if dialog:
                    dialog.destroy()
                self._abort(str(e))
            else:
                log.info("Authenticated user %s" % username)
                self._force_username = None

                if dialog.remember.get_active():
                    get_utility(ICookieFile).store(user.username,
                                                   user.pw_hash)

                if dialog:
                    dialog.destroy()

                return user

        if dialog:
            dialog.destroy()
        raise LoginError(_("Depleted attempts of authentication"))

    #
    # Exit strategies
    #

    def _abort(self, msg=None, title=None):
        if msg:
            warning(msg)
        raise SystemExit
