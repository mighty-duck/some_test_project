from sqlalchemy import create_engine
from sqlalchemy import Table, Column, Integer, MetaData
from sqlalchemy.orm import sessionmaker
from enum import Enum
from bottle import Bottle, run, request
from json import dumps
import math


class Converter:
    """
         Класс для преобразования из десятиричной системы счисления в систему счисления построенную на основе
         алфавита ключа. Идея использования данного класса такая - если каждый символ ключа это разряд, то у каждого
         разряда есть свой вес и своё значение, а значит его можно преобразовать к числу. Это число в дальнейшем
         можно хранить в базе. Выигрыша по объёму хранения данных это не даст, так как ключ это 4 char'а а int
         эквивалентем им же, но это позволяет удобно работать с ключами. Например представить их как последовательность
         чисел, что используется в дальнейшем.
    """
    def __init__(self):
        self.alphabet = \
            [chr(x) for x in range(ord('0'), ord('9') + 1)] + \
            [chr(x) for x in range(ord('a'), ord('z') + 1)] + \
            [chr(x) for x in range(ord('A'), ord('Z') + 1)]

        self._max_value = int(math.pow(len(self.alphabet), 4) - 1)

    def int_to_string(self, data):
        """
            преобразование числа, хранимого в базе к ключу, который видит пользователь
        :param data: ключ в виде числа
        :return:
        """
        if data < len(self.alphabet):
            return self.alphabet[data]
        else:
            return self.int_to_string(data // len(self.alphabet)) + self.alphabet[data % len(self.alphabet)]

    def string_to_int(self, data):
        """
            преобразование ключа, который видит пользователь, к числу хранимому в базе
        :param data: ключ в виде числа
        :return:
        """
        acum = 0
        for cort in enumerate(reversed(data)):
            acum += math.pow(len(self.alphabet), cort[0]) * self.alphabet.index(cort[1])

        return int(acum)

    @property
    def max_value(self):
        """
            максимальное число обрабатываемых ключей
        :return:
        """
        return self._max_value


class DB:
    """
        Данный класс инкапсулирует всб работу с базой данных.
    """
    class KeyStatus(Enum):
        Unused = 0
        Gived = 1
        Used = 2

    def __init__(self):
        """
            Конструктор базы данных. В реальных условиях должен создавить базу или подключаться к ней.
            Поскольку пример демонстрационный, просто создаю базу в памяти.

            Использую sqlalchemy для быстрого создания таблиц. Не использую возможности orm, так как
            в данной ситуации, как мне кажется, проще написать sql запросы.
        """

        self._converter = Converter()
        self._engine = create_engine('sqlite:///:memory:', echo=False)
        self._metadata = MetaData()

        self._gived_keys = Table(
            'gived_keys',
            self._metadata,
            Column('key', Integer)
        )

        self._current_key = Table(
            'current_key',
            self._metadata,
            Column('key', Integer)
        )

        self._metadata.create_all(self._engine)
        self._sessionmaker = sessionmaker(bind=self._engine)

        self.session = self._sessionmaker()

        self.execute('''
            INSERT INTO current_key (key) VALUES (0);     
        ''')

    def execute(self, sql):
        return self.session.execute(sql)

    def _get_current_key(self):
        """
            Получает текущее значение ключа, который может быть выдан в данный момент.

        :return:
        """
        return self.execute('''
            SELECT key FROM current_key LIMIT 1;
        ''').first()[0]

    def unused_keys_number(self):
        """
            Возвращает число ключей, которые ещё можно выдать пользователю.

        :return:
        """
        return self._converter.max_value - self._get_current_key()

    def get_unused_key(self):
        """
           Возращает первый номер ключа, который ещё не выдывался пользователю.

        :return:
        """
        digit_notation = self._get_current_key()
        string_represent = self._converter.int_to_string(digit_notation)
        return string_represent if len(string_represent) == 4 else string_represent.zfill(4)

    def _to_digit_notation(self, key):
        string_represent = key.lstrip('0')
        return self._converter.string_to_int(string_represent)

    def _get_key_status(self, digit_notation):
        """
            Получает текущее состояние ключа: использован, не использован, выдан на данный момент.

            Идея функции заключается в следующем: ключи выдаются последовательно и всегда известно какие
            ключи точно не выдавались. Это первый if. Если ключ был выдан но не закрыт, то он лежит в таблице
            gived_keys, поэтому проверяем нет ли его там. Если его нет, то ключ уже был закрыт. Если есть, то
            закрытия ещё не произошло.

        :param digit_notation: числовое представление ключа.
        :return:
        """
        c_key = self._get_current_key()

        if c_key <= digit_notation:
            return DB.KeyStatus.Unused
        else:
            if self.execute('''
                select exists(select key from gived_keys where key = {key}) as "key_exist"
            '''.format(
                key=digit_notation
            )).first()['key_exist']:
                return DB.KeyStatus.Gived
            else:
                return DB.KeyStatus.Used

    def get_key_status(self, key):
        """
            Получает текущее состояние ключа: использован, не использован, выдан на данный момент.

        :param key: ключ в пользовательском (текстовом) представлении.
        :return:
        """
        return self._get_key_status(self._to_digit_notation(key))

    def give_out_key(self):
        """
            Выдаёт следующий свободный ключ.

        :return:
        """
        unused_key = self.get_unused_key()
        uk_digit_notation = self._to_digit_notation(unused_key)
        self.execute('''
            UPDATE current_key SET key = key + 1;
        ''')

        self.execute('''
            INSERT INTO gived_keys (key) VALUES ({key});
        '''.format(
            key=uk_digit_notation
        ))

        return unused_key

    def put_out_key(self, key):
        """
            Закрывает произвольный открытый ключ.

        :param key: ключ в пользовательском (текстовом) представлении.
        :return:
        """
        try:
            digit_notation = self._to_digit_notation(key)
        except ValueError:
            return False

        key_status = self._get_key_status(digit_notation)

        if key_status is DB.KeyStatus.Gived:
            self.execute('''
                delete from gived_keys 
                where key = {key}
            '''.format(
                key=digit_notation
            ))

            return True
        else:
            return False


db = DB()
app = Bottle()


@app.route('/')
def index():
    message = '''
        <h2>hello!</h2>
        <h4>usage:
        <ul>
            <li>/give_out_key/</li>
            <li>/put_out_key/</li>
            <li>/keys_left/</li>
            <li>/key_info/</li>
        </ul>
        </h4>
    '''

    return message


@app.route('/give_out_key/')
def give_out_key():
    key = db.give_out_key()
    return dumps({'key': key})


@app.route('/put_out_key/')
def put_out_key():
    if 'key' in request.POST:
        return dumps({'result': db.put_out_key(request.GET.key)})


@app.route('/keys_left/')
def keys_left():
    return dumps({'keys_left': db.unused_keys_number()})


@app.route('/key_info/')
def keys_left():
    if 'key' in request.params:
        return dumps({'key_info': db.get_key_status(request.params.key).name.lower()})


run(app, host='localhost', port=5000)
