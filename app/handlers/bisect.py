# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""The request handler for bisect URLs."""

import tornado

from functools import partial
from tornado.web import asynchronous

from handlers.base import BaseHandler
from handlers.common import NOT_VALID_TOKEN
from handlers.response import HandlerResponse
from taskqueue.tasks import boot_bisect

from utils.db import find_one

from models import (
    BISECT_COLLECTION,
    BOOT_COLLECTION,
    DOC_ID_KEY,
)

BISECT_COLLECTIONS = [
    BOOT_COLLECTION,
]


class BisectHandler(BaseHandler):
    """Handler used to trigger bisect operations on the data."""

    def __init__(self, application, request, **kwargs):
        super(BisectHandler, self).__init__(application, request, **kwargs)

    @asynchronous
    def get(self, *args, **kwargs):
        self.executor.submit(
            partial(self.execute_get, *args, **kwargs)
        ).add_done_callback(
            lambda future:
            tornado.ioloop.IOLoop.instance().add_callback(
                partial(self._create_valid_response, future.result())
            )
        )

    @property
    def collection(self):
        return BISECT_COLLECTION

    def execute_get(self, *args, **kwargs):
        """This is the actual GET operation.

        It is done in this way so that subclasses can implement a different
        token authorization if necessary.
        """
        response = None

        # TODO: handle fields data structure.
        if self.validate_req_token("GET"):
            if kwargs:
                collection = kwargs.get("collection", None)
                doc_id = kwargs.get("id", None)
                if all([collection, doc_id]):
                    bisect_result = find_one(
                        self.db[self.collection], doc_id, field=DOC_ID_KEY
                    )
                    if bisect_result:
                        response = HandlerResponse(200)
                        response.result = bisect_result
                    else:
                        response = self._get_bisect(collection, doc_id)
                else:
                    response = HandlerResponse(400)
            else:
                response = HandlerResponse(400)
        else:
            response = HandlerResponse(403)
            response.reason = NOT_VALID_TOKEN

        return response

    def _get_bisect(self, collection, doc_id):
        """Retrieve the bisect data.

        :param collection: The name of the collection to operate on.
        :type collection: str
        :param doc_id: The ID of the document to execute the bisect on.
        :type doc_id: str
        :return A `HandlerResponse` object.
        """
        response = None

        if collection in BISECT_COLLECTIONS:
            db_options = self.settings["dboptions"]

            if collection == BOOT_COLLECTION:
                response = self.execute_boot_bisect(doc_id, db_options)
        else:
            response = HandlerResponse(400)
            response.reason = (
                "Provided bisect collection '%s' is not valid" % collection
            )

        return response

    @staticmethod
    def execute_boot_bisect(doc_id, db_options):
        """Execute the boot bisect operation.

        :param doc_id: The ID of the document to execute the bisect on.
        :type doc_id: str
        :param db_options: The mongodb database connection parameters.
        :type db_options: dict
        :return A `HandlerResponse` object.
        """
        response = HandlerResponse()

        result = boot_bisect.apply_async([doc_id, db_options])
        while not result.ready():
            pass

        response.status_code, response.result = result.get()
        if response.status_code == 404:
            response.reason = "Boot report not found"
        elif response.status_code == 400:
            response.reason = "Boot report cannot be bisected: is it failed?"
        return response
