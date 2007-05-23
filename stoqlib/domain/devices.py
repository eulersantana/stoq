# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2005-2007 Async Open Source <http://www.async.com.br>
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
## Author(s):   Henrique Romano <henrique@async.com.br>
##              Johan Dahlin    <jdahlin@async.com.br>
##
"""
Domain classes related to stoqdrivers package.
"""

from sqlobject.col import (UnicodeCol, IntCol, ForeignKey, BoolCol, BLOBCol,
                           DateTimeCol, StringCol)
from sqlobject.joins import MultipleJoin
from sqlobject.sqlbuilder import AND
from zope.interface import implements
from stoqdrivers.constants import describe_constant
from stoqdrivers.enum import PaymentMethodType, UnitType, TaxType
from stoqdrivers.devices.printers.fiscal import FiscalPrinter
from stoqdrivers.devices.printers.cheque import ChequePrinter
from stoqdrivers.devices.scales.scales import Scale
from stoqdrivers.devices.serialbase import VirtualPort, SerialPort

from stoqlib.database.columns import DecimalCol
from stoqlib.database.runtime import get_current_station
from stoqlib.domain.base import Domain
from stoqlib.domain.interfaces import IActive, IDescribable
from stoqlib.exceptions import DatabaseInconsistency, DeviceError
from stoqlib.lib.translation import stoqlib_gettext

_ = stoqlib_gettext

class DeviceConstant(Domain):
    """
    Describes a device constant

    The constant_value field is only used by custom tax codes,
    eg when constant_type is TYPE_TAX and constant_enum is TaxType.CUSTOM

    @cvar constant_type: the type of constant
    @cvar constant_name: name of the constant
    @cvar constant_enum: enum value of the constant
    @cvar constant_value: value of the constant, only for TAX constants for
      which it represents the tax percentage
    @cvar device_value: the device value
    @cvar device_settings: settings
    """
    implements(IDescribable)

    constant_type = IntCol()
    constant_name = UnicodeCol()
    constant_value = DecimalCol(default=None)
    constant_enum = IntCol(default=None)
    device_value = BLOBCol()
    device_settings = ForeignKey("DeviceSettings")

    (TYPE_UNIT,
     TYPE_TAX,
     TYPE_PAYMENT) = range(3)

    constant_types = {TYPE_UNIT: _(u'Unit'),
                      TYPE_TAX: _(u'Tax'),
                      TYPE_PAYMENT: _(u'Payment')}

    def get_constant_type_description(self):
        """
        Describe the type in a human readable form
        @returns: description of the constant type
        @rtype: str
        """
        return DeviceConstant.constant_types[self.constant_type]

    @classmethod
    def get_custom_tax_constant(cls, device_settings, constant_value, conn):
        """
        Fetches a custom tax constant.

        @param device_settings: settings to fetch constants from
        @type device_settings: L{DeviceSettings}
        @param constant_enum: tax enum code
        @type constant_enum: int
        @param conn: a database connection
        @returns: the constant
        @rtype: L{DeviceConstant}
        """
        return DeviceConstant.selectOneBy(
            device_settings=device_settings,
            constant_type=DeviceConstant.TYPE_TAX,
            constant_enum=int(TaxType.CUSTOM),
            constant_value=constant_value,
            connection=conn)

    @classmethod
    def get_tax_constant(cls, device_settings, constant_enum, conn):
        """
        Fetches a tax constant.
        Note that you need to use L{Device_settings.get_custom_tax_constant}
        for custom tax constants.

        @param device_settings: settings to fetch constants from
        @type device_settings: L{DeviceSettings}
        @param constant_enum: tax enum code
        @type constant_enum: int
        @param conn: a database connection
        @returns: the constant
        @rtype: L{DeviceConstant}
        """
        if constant_enum == TaxType.CUSTOM:
            raise ValueError("Use get_custom_tax_constant for custom "
                             "tax codes")
        return DeviceConstant.selectOneBy(
            device_settings=device_settings,
            constant_type=DeviceConstant.TYPE_TAX,
            constant_enum=int(constant_enum),
            connection=conn)

    #
    # IDescribable
    #

    def get_description(self):
        return self.constant_name

class DeviceSettings(Domain):
    implements(IActive)

    type = IntCol()
    brand = UnicodeCol()
    model = UnicodeCol()
    device = IntCol()
    station = ForeignKey("BranchStation")
    is_active = BoolCol(default=True)
    constants = MultipleJoin('DeviceConstant')

    (DEVICE_SERIAL1,
     DEVICE_SERIAL2,
     DEVICE_PARALLEL) = range(1, 4)

    (SCALE_DEVICE,
     FISCAL_PRINTER_DEVICE,
     CHEQUE_PRINTER_DEVICE) = range(1, 4)

    device_descriptions = {DEVICE_SERIAL1: _('Serial port 1'),
                           DEVICE_SERIAL2: _('Serial port 2'),
                           DEVICE_PARALLEL: _('Parallel port')}

    port_names = {DEVICE_SERIAL1: '/dev/ttyS0',
                  DEVICE_SERIAL2: '/dev/ttyS1',
                  DEVICE_PARALLEL: '/dev/parport'}

    device_types = {SCALE_DEVICE: _('Scale'),
                    FISCAL_PRINTER_DEVICE: _('Fiscal Printer'),
                    CHEQUE_PRINTER_DEVICE: _('Cheque Printer')}

    #
    # Domain
    #

    def clone(self):
        clone = super(DeviceSettings, self).clone()
        for constant in self.constants:
            constant.clone().device_settings = clone

        return clone

    @classmethod
    def delete(cls, id, connection):
        obj = DeviceSettings.get(id, connection=connection)
        for constant in obj.constants:
            DeviceConstant.delete(constant.id, connection=connection)
        super(DeviceSettings, cls).delete(id, connection)


    #
    # Public API
    #

    def create_fiscal_printer_constants(self):
        """
        Creates constants for a fiscal printer
        This can be called multiple times
        """
        if self.type != DeviceSettings.FISCAL_PRINTER_DEVICE:
            raise DeviceError("Device %r is not a fiscal printer" % self)

        # We only want to populate 'empty' objects.
        if self.constants:
            return

        conn = self.get_connection()
        driver = self.get_interface()
        constants = driver.get_constants()
        for constant in constants.get_items():
            constant_value = None
            if isinstance(constant, PaymentMethodType):
                constant_type = DeviceConstant.TYPE_PAYMENT
            elif isinstance(constant, UnitType):
                constant_type = DeviceConstant.TYPE_UNIT
            else:
                continue

            DeviceConstant(constant_type=constant_type,
                           constant_name=describe_constant(constant),
                           constant_value=constant_value,
                           constant_enum=int(constant),
                           device_value=constants.get_value(constant, None),
                           device_settings=self,
                           connection=conn)

        for constant, device_value, value in constants.get_tax_constants():
            if constant == TaxType.CUSTOM:
                constant_name = _('%d %%') % value
            else:
                constant_name = describe_constant(constant)
            DeviceConstant(constant_type=DeviceConstant.TYPE_TAX,
                           constant_name=constant_name,
                           constant_value=value,
                           constant_enum=int(constant),
                           device_value=device_value,
                           device_settings=self,
                           connection=conn)

    def get_constants_by_type(self, constant_type):
        """
        Fetchs a list of constants for the current DeviceSettings object.
        @param constant_type: type of constant
        @type constant_type: L{DeviceConstant}
        @returns: list of constants
        """
        return DeviceConstant.selectBy(device_settings=self,
                                       constant_type=constant_type,
                                       connection=self.get_connection())

    def get_payment_constant(self, constant_enum):
        """
        @param constant_enum:
        @returns: the payment constant
        @rtype: L{DeviceConstant}
        """
        return DeviceConstant.selectOneBy(
            device_settings=self,
            constant_type=DeviceConstant.TYPE_PAYMENT,
            constant_enum=int(constant_enum),
            connection=self.get_connection())

    def get_tax_constant_for_device(self, sellable):
        """
        Returns a tax_constant for a device
        Raises DeviceError if a constant is not found

        @param sellable: sellable which has the tax codes
        @type sellable: L{stoqlib.domain.sellable.Sellable}
        @returns: the tax constant
        @rtype: L{DeviceConstant}
        """

        sellable_constant = sellable.get_tax_constant()
        if sellable_constant is None:
            raise DeviceError("No tax constant set for sellable %r" % sellable)

        conn = self.get_connection()
        if sellable_constant.tax_type == TaxType.CUSTOM:
            constant = DeviceConstant.get_custom_tax_constant(
                self, sellable_constant.tax_value, conn)
            if constant is None:
                raise DeviceError(_(
                    "fiscal printer is missing a constant for the custom "
                    "tax constant %r") %  (sellable_constant.description,))
        else:
            constant = DeviceConstant.get_tax_constant(
                self, sellable_constant.tax_type, conn)
            if constant is None:
                raise DeviceError(_(
                    "fiscal printer is missing a constant for tax "
                    "constant %r") %  (sellable_constant.description,))

        return constant

    def get_printer_description(self):
        return "%s %s" % (self.brand.capitalize(), self.model)

    def get_device_description(self, device=None):
        return DeviceSettings.device_descriptions[device or self.device]

    # TODO: rename to get_device_name
    def get_port_name(self, device=None):
        return DeviceSettings.port_names[device or self.device]

    def get_device_type_name(self, type=None):
        return DeviceSettings.device_types[type or self.type]

    # XXX: Maybe stoqdrivers can implement a generic way to do this?
    def get_interface(self):
        """ Based on the column values instantiate the stoqdrivers interface
        for the device itself.
        """
        if self._is_a_virtual_printer():
            port = VirtualPort()
        else:
            port = SerialPort(device=self.get_port_name())

        if self.type == DeviceSettings.FISCAL_PRINTER_DEVICE:
            return FiscalPrinter(brand=self.brand, model=self.model, port=port)
        elif self.type == DeviceSettings.CHEQUE_PRINTER_DEVICE:
            return ChequePrinter(brand=self.brand, model=self.model, port=port)
        elif self.type == DeviceSettings.SCALE_DEVICE:
            return Scale(brand=self.brand, model=self.model,
                         device=self.get_port_name())
        raise DatabaseInconsistency("The device type referred by this "
                                    "record (%r) is invalid, given %r."
                                    % (self, self.type))

    def is_a_printer(self):
        return self.type in (DeviceSettings.FISCAL_PRINTER_DEVICE,
                             DeviceSettings.CHEQUE_PRINTER_DEVICE)

    def is_a_fiscal_printer(self):
        return self.type == DeviceSettings.FISCAL_PRINTER_DEVICE

    def is_valid(self):
        return (None not in (self.model, self.device, self.brand, self.station)
                and self.type in DeviceSettings.device_types)

    @classmethod
    def get_by_station_and_type(cls, conn, station, type):
        """
        Fetch all non-virtual settings for a specific station and type.

        @param conn: a database connection
        @param station: a BranchStation instance
        @param type: device type
        """
        return cls.select(
            AND(cls.q.stationID == station,
                cls.q.type == type,
                cls.q.brand != 'virtual'),
        connection=conn)

    @classmethod
    def get_virtual_printer_settings(cls, conn, station):
        """
        Fetch the virtual printer settings for a station. None will
        be return if the station lacks a setting.
        @param conn: a database connection
        @param station: a BranchStation instance
        """
        return cls.selectOneBy(
            station=station,
            brand="virtual",
            type=DeviceSettings.FISCAL_PRINTER_DEVICE,
            connection=conn)


    @classmethod
    def get_scale_settings(cls, conn):
        """
        Get the scale device settings for the current station
        @param conn: a database connection
        @returns: a L{DeviceSettings} object or None if there is none
        """
        station = get_current_station(conn)
        return cls.selectOneBy(
            connection=conn,
            station=station,
            type=cls.SCALE_DEVICE)

    #
    # IActive implementation
    #

    def inactivate(self):
        self.is_active = False

    def activate(self):
        self.is_active = True

    def get_status_string(self):
        if self.is_active:
            return _(u'Active')
        return _(u'Inactive')

    #
    # Private
    #

    def _is_a_virtual_printer(self):
        return (self.is_a_printer() and self.brand == "virtual" and
                self.model == "Simple")


class FiscalDayTax(Domain):
    """
    This represents the information that needs to be used to
    generate a Sintegra file of type 60M.
    @cvar code: four bytes, either the percental of the tax, 1800 for 18%
    or one of::
       - I: Isento
       - F: Substitucao
       - N: Nao tributado
       - ISS: ISS
       - CANC: Cancelled
       - DESC: Discount
    """
    fiscal_day_history = ForeignKey('FiscalDayHistory')
    code = StringCol()
    value = DecimalCol()


class FiscalDayHistory(Domain):
    """
    This represents the information that needs to be used to
    generate a Sintegra file of type 60A.
    """
    emission_date = DateTimeCol()
    device = ForeignKey('DeviceSettings')
    serial = StringCol()
    serial_id = IntCol()
    coupon_start = IntCol()
    coupon_end = IntCol()
    cro = IntCol()
    crz = IntCol()
    period_total = DecimalCol()
    total = DecimalCol()
    taxes = MultipleJoin('FiscalDayTax')
