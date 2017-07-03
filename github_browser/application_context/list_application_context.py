from datetime import datetime, timedelta, timezone

import requests

from github_browser.time_adapter import get_time_range, transform_date, sort_by_creation_date, load_api_date
from . import ApplicationContext


class ListApplicationContext(ApplicationContext):
    PATH_SEARCH = '/search/repositories'
    PATH_EVENTS = '/events'

    def __init__(self, n: int, lang: str = None, sort: str = 'default', extended_output=False):
        self.entry_number = n
        self.selected_language = lang
        self.sort_type = sort
        self.extended_output = extended_output
        self._repository_list = None
        self._output_text = None

    def get_query_str(self, time=get_time_range(30)) -> str:
        time_lower, time_higher = time
        language_query = "" if self.selected_language is None else ("+language:" + self.selected_language)

        query_build_str = ['q=created:\"%s+..+%s\"%s' % (time_lower, time_higher, language_query)]
        query_build_str.append('per_page=100')

        # If sort type is default then we should query with updated
        # as 'default' is CUSTOM type not supported by Octopus API
        query_build_str.append('sort=%s' % ('updated' if self.sort_type == 'default' else self.sort_type))

        return '?' + '&'.join(query_build_str)

    def get_sanitized_data(self) -> str:
        if self._output_text is not None:
            return self._output_text
        elif self._repository_list is None:
            return ""
        else:
            # previously geathered repository
            repositories = self._repository_list

            output_text_buffer = list()
            output_text_buffer.append("Total entries found: %s" % len(repositories))
            output_text_buffer.append("----------------------------------------")
            if self.extended_output:
                output_text_buffer.append('\n'.join("#%s\t\t\t%s\t\t\t\t\t\t%s" %
                                                    (idx, i['full_name'], transform_date(i['created_at']))
                                                    for idx, i in enumerate(repositories)))
            else:
                output_text_buffer.append('\n'.join(i['full_name'] for i in repositories))

            self._output_text = '\n'.join(output_text_buffer)
            return self._output_text

    def create_query(self, time_range):
        return ''.join([ApplicationContext.ROOT_ENDPOINT, self.PATH_SEARCH, self.get_query_str(time_range)])

    def run(self):
        # Search repositories created in last 10 minutes
        # If we get more entries then expected, sort them and take first n entries
        # If we get less, multiply search range
        time_diff = 10
        time_range = get_time_range(time_diff)
        request_url = self.create_query(time_range)

        # Collection of items gathered throughout api calls and processed for output
        items = []
        total_repo_count = 0
        if self.sort_type == 'default':
            while True:
                # Gather items and sort them by creation date
                # GitHub api doesn't support sort by creation date
                request = requests.get(request_url)
                content = request.json()

                try:
                    items.extend(content['items'])
                except KeyError:  # This error repeats if API limit is exceeded
                    print("Error, API limit is most likely exceeded, try again in a bit.")
                    print("Here is message:")
                    print(content['message'])
                    exit(2)

                total_repo_count += content['total_count']

                if total_repo_count > self.entry_number:
                    # each request can only contain up to 100 entries
                    # gather them with multiple requests by traversing the list like structure
                    try:
                        request_url = request.links['next']['url']
                        continue
                    except KeyError:
                        break
                elif total_repo_count == self.entry_number:
                    break
                else:
                    # Our search query contains less item then we need
                    # Increase range for filtering and re-try
                    try:
                        if len(items) == 0:
                            # Multiply search range by 6 if there are no entries
                            time_diff *= 6
                            time_range = get_time_range(time_diff)
                        else:
                            # Multiply search range by 3 starting from creation date of last entry in range
                            time_diff *= 3
                            last_date = min(items, key=sort_by_creation_date)['created_at']
                            # Reduced by 1 second to ensure no duplicates
                            time_range = get_time_range(time_diff,
                                                        time_higher=load_api_date(last_date) - timedelta(seconds=1))

                        request_url = self.create_query(time_range)
                        continue
                    except KeyError:
                        break

            items = sorted(items, key=sort_by_creation_date, reverse=True)

        else:
            request = requests.get(request_url)
            content = request.json()
            items.extend(content['items'])

        self._repository_list = items[0:self.entry_number]
