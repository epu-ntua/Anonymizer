__author__ = 'dipap'

from util import configuration
from connections import connection_manager
from pydoc import locate


class PropertyManagerException(Exception):
    """
    Exceptions caused by the property manager
    """
    pass


class UserManagerException(Exception):
    """
    Exceptions caused by the user manager
    """
    pass


class ProviderNotFound(Exception):
    """
    A data provider described in the configuration was not found
    """
    pass


class ProviderMethodNotFound(Exception):
    """
    A method of a data provider described in the configuration was not found
    """
    pass


class PropertyNotFoundException(Exception):
    """
    Exception for when a property name described in the configuration is not found
    """
    pass


class Property:
    """
    A single property
    """
    def __init__(self, source, user_fk, name=None, tp=None):
        self.source = source
        self.table = source.split('@')[0].split('.')[0]
        self.column = source.split('@')[0].split('.')[1]
        if not name:
            self.name = self.column
        else:
            self.name = name

        if tp:
            self.type = tp
        else:
            self.tp = 'string'

        if not self.is_generated():
            # find responsible db connection
            conn_name = source.split('@')[1]
            for c in connection_manager.connections:
                if c['ID'] == conn_name:
                    self.connection = c['conn']
                    break

            if not self.connection:
                raise PropertyManagerException('Database not found in test_config.json: ' + conn_name)

            if user_fk:
                self.user_fk = Property(user_fk, user_fk=None)
            else:
                self.user_fk = None
        else:
            # load provider class
            cls_name = 'anonymizer.datasource.providers.' + self.source.split('.')[0][1:]
            cls = locate(cls_name)
            if not cls:
                raise ProviderNotFound('Provider ' + cls_name + ' was not found')

            # load provider class method
            fn_name = self.source.split('.')[1].split('(')[0]
            try:
                self.fn = getattr(cls, fn_name)
            except AttributeError:
                raise ProviderMethodNotFound('Provider method ' + fn_name + ' was not found')

    def is_generated(self):
        return self.source[0] in ['^']

    def full(self):
        return self.table + '.' + self.column


class PropertyManager:
    """
    The manager for all properties
    """
    def __init__(self):
        self.user_pk = Property(configuration.data['sites'][0]['user_pk'], user_fk=None)

        self.properties = [self.user_pk]

        for property_info in configuration.data['sites'][0]['properties']:
            if 'user_fk' in property_info:
                user_fk = property_info['user_fk']
            else:
                user_fk = None

            prop = Property(property_info['source'], user_fk=user_fk, name=property_info['name'], tp=property_info['type'])
            self.properties.append(prop)

    def info(self, row):
        idx = 0
        result = {}

        # fill property values from database
        for prop in self.properties:
            if not prop.is_generated():
                result[prop.name] = row[idx]
                idx += 1

        # generate other properties
        for prop in self.properties:
            if prop.is_generated():
                result[prop.name] = 'test'

                # get function argument
                fn_args = prop.source.split('.')[1].split('(')[1][:-1].split(',')

                # search for 'special' arguments the must be replaced
                # e.g property names like `@age`
                for idx, fn_arg in enumerate(fn_args):
                    if fn_arg:
                        # replace property names with their values
                        if fn_arg[0] == '@':
                            try:
                                fn_args[idx] = result[fn_arg[1:]]
                            except KeyError:
                                raise PropertyNotFoundException('Property "' + fn_arg[1:] + '" was not found.')

                # apply function and save the result
                result[prop.name] = prop.fn(fn_args)

        return result

    def query(self):
        select_clause = 'SELECT ' + \
                        ','.join([prop.full() + ' AS ' + prop.name for prop in self.properties if not prop.is_generated()]) + ' '
        from_clause = 'FROM {0} '.format(self.user_pk.table)
        join_clause = ''
        for prop in self.properties:
            if not prop.is_generated():
                if prop.user_fk:
                    join_clause += 'LEFT OUTER JOIN {0} ON {1}={2} '\
                        .format(prop.table, prop.user_fk.full(), self.user_pk.full())

        return select_clause + from_clause + join_clause

    def all(self):
        query = self.query()

        # execute query & return results
        return [self.info(row) for row in self.user_pk.connection.cursor().execute(query).fetchall()]

    def filter(self, filters):
        if not filters:
            return self.all()

        query = self.query()

        # create where clause
        if not type(filters) == list:
            filters = [filters]

        where_clause = 'WHERE ' + ' AND '.join(filters)

        query += where_clause

        # execute query & return results
        return [self.info(row) for row in self.user_pk.connection.cursor().execute(query).fetchall()]

    def get(self, pk):
        where_clause = 'WHERE {0}={1}'.format(self.user_pk.full(), pk)

        # construct full query
        query = self.query() + where_clause

        # execute query & return results
        return self.info(self.user_pk.connection.cursor().execute(query).fetchone())


class UserManager:
    """
    The User manager is responsible for fetching and filtering user information
    """
    def __init__(self):
        self.pm = PropertyManager()

    def get(self, pk):
        # Ensures the user exists
        query = "SELECT {0} AS pk FROM {1} WHERE pk={2}".format(self.pm.user_pk.full(), self.pm.user_pk.table, pk)
        result = self.pm.user_pk.connection.cursor().execute(query).fetchall()

        # check uniqueness
        if len(result) == 0:
            raise UserManagerException('User with id={0} does not exist'.format(pk))
        elif len(result) > 1:
            raise UserManagerException('More than one users with id={0} where found'.format(pk))

        return self.pm.get(pk)

    def filter(self, filters):
        return self.pm.filter(filters)

    def all(self):
        return self.pm.all()

user_manager = UserManager()
