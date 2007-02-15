# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2007 Async Open Source
##
## This program is free software; you can redistribute it and/or
## modify it under the terms of the GNU Lesser General Public License
## as published by the Free Software Foundation; either version 2
## of the License, or (at your option) any later version.
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
##
## Author(s):       Johan Dahlin                <jdahlin@async.com.br>
##
##

from stoqlib.domain.service import Service
from stoqlib.domain.sellable import BaseSellableInfo
from stoqlib.domain.interfaces import ISellable
from stoqlib.importers.csvimporter import CSVImporter

class ServiceImporter(CSVImporter):
    fields = ['description',
              'barcode',
              'price',
              'cost',
              ]

    def process_one(self, data, fields, trans):
        service = Service(connection=trans)
        sellable_info = BaseSellableInfo(connection=trans,
                                         description=data.description,
                                         price=data.price)
        service.addFacet(ISellable, connection=trans,
                         base_sellable_info=sellable_info,
                         cost=data.cost, barcode=data.barcode)
