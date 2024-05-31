import hashlib
import json
import os
import re
import struct
import time
import urllib.parse
import zipfile

import requests

domain = 'ltn.hitomi.la'
galleryblockextension = '.html'
galleryblockdir = 'galleryblock'
nozomiextension = '.nozomi'

index_dir = 'tagindex'
galleries_index_dir = 'galleriesindex'
languages_index_dir = 'languagesindex'
nozomiurl_index_dir = 'nozomiurlindex'


class Hitomi:
    def __init__(self, storage_path_fmt=None):
        self.index_versions = {
            'init': False,
            index_dir: '',
            galleries_index_dir: '',
            languages_index_dir: '',
            nozomiurl_index_dir: ''
        }
        if storage_path_fmt is None:
            self.storage_path = os.curdir
            print(f'下载路径未配置，默认采用当前工作路径:{self.storage_path}')
        elif not os.path.exists(storage_path_fmt):
            print('配置的下载路径不存在，创建')
            os.mkdir(self.storage_path)
        print('搜索模块初始化')
        self.refresh_version()
        print('搜索模块初始化完成')
        self.gg_list = []
        self.fucking_b = ''
        self.fucking_o = None
        print('下载模块初始化')
        self.set_gg()
        print('下载模块初始化完成')

    @staticmethod
    def get_gallery_info(gallery_id):
        req_url = f'https://ltn.hitomi.la/galleries/{gallery_id}.js'
        response = requests.get(req_url)
        if response.status_code != 200:
            raise ValueError(f"Error getting gallery info: {response.status_code}")
        else:
            # 使用正则表达式匹配 galleryinfo 变量的 JSON 对象
            if 'galleryinfo' not in response.text:
                print(response.text)
                raise ValueError("galleryinfo not found")
            match = re.search(r'{.*', response.text, re.DOTALL)
            # 提取匹配的 JSON 字符串
            json_str = match.group(0)
            # 解析 JSON 字符串为 Python 字典
            try:
                galleryinfo_dict = json.loads(json_str)
            except json.JSONDecodeError as e:
                raise ValueError(f"Error decoding JSON: {e}")
            return galleryinfo_dict

    def set_gg(self, add_timestamp=False):
        if add_timestamp:
            gg_url = f'https://ltn.hitomi.la/gg.js?_={int(time.time() * 1000)}'
        else:
            gg_url = 'https://ltn.hitomi.la/gg.js?'
        gg_resp = requests.get(gg_url).text.split('\n')
        gg_dict = {'gg_list': [], 'fucking_b': '', 'fucking_o': None}
        for line in gg_resp:
            if line.startswith('case'):
                gg_dict['gg_list'].append(int(line[5:][:-1]))
            elif line.startswith('b:'):
                gg_dict['fucking_b'] = str(line[4:][:-1])
            elif line.startswith('o = 1'):
                gg_dict['fucking_o'] = True
            elif line.startswith('o = 0'):
                gg_dict['fucking_o'] = False
        self.gg_list = gg_dict['gg_list']
        self.fucking_b = gg_dict['fucking_b']
        self.fucking_o = gg_dict['fucking_o']

    def refresh_version(self):
        for version_name, version in self.index_versions.items():
            _ = 0
            for _ in range(10):
                url = f'http://{domain}/{version_name}/version?_={int(time.time() * 1000)}'
                response = requests.get(url)
                version = response.text
                if not version:
                    print(f'{version_name} failed', _)
                    time.sleep(1)
                else:
                    self.index_versions[version_name] = version
                    break
            if version == '':
                raise ConnectionError(f'{version_name} failed totally')
        self.index_versions['init'] = True

    def url_from_url(self, url, base):
        def subdomain_from_url(inner_url, inner_base):
            if not self.gg_list or self.fucking_o is None:
                raise ValueError('反爬虫破解未配置')

            def decide_gg(inner_g):
                if inner_g in self.gg_list:
                    return 1 if self.fucking_o else 0
                return 0 if self.fucking_o else 1

            retval = 'b'
            if inner_base:
                retval = inner_base
            b = 16
            match = re.search(r'/[0-9a-f]{61}([0-9a-f]{2})([0-9a-f])', inner_url)
            if not match:
                return 'a'
            m1, m2 = match.group(1), match.group(2)
            g = int(m2 + m1, b)
            return chr(97 + decide_gg(g)) + retval

        return re.sub(r'//..?\.hitomi\.la/', f'//{subdomain_from_url(url, base)}.hitomi.la/', url)

    def get_download_urls(self, info):
        def url_from_hash(galleryid, image, inner_dir=None, ext=None):
            ext = ext or inner_dir or image['name'].split('.').pop()
            inner_dir = inner_dir or 'images'
            if self.fucking_b == 0:
                raise ValueError('Invalid fucking_b')

            def gg_s(h):
                m = re.search(r'(..)(.)$', h)
                if m:
                    return str(int(m.group(2) + m.group(1), 16))
                return ''

            return f'https://a.hitomi.la/{inner_dir}/{self.fucking_b}{gg_s(image["hash"])}/{image["hash"]}.{ext}'

        download_urls = {}
        for file in info['files']:
            image_name = re.sub(r'\.[^.]+$', '.webp', file['name'])
            download_urls[image_name] = self.url_from_url(url_from_hash(info['id'], file, 'webp', None), 'a')
        return download_urls

    @staticmethod
    def get_url_at_range(url, inner_range):
        for _ in range(10):
            headers = {
                'Range': f'bytes={inner_range[0]}-{inner_range[1]}'
            }
            time.sleep(0.5)
            response = requests.get(url, headers=headers)
            if response.status_code == 200 or response.status_code == 206:
                return response.content
            elif response.status_code == 503:
                print('503 ', _)
                time.sleep(3)
            else:
                raise Exception(
                    f"get_url_at_range({url}, {inner_range}) failed, response.status_code: {response.status_code}")
        raise ConnectionError('重试次数过多')

    def get_node_at_address(self, field, address):
        max_node_size = 464

        def decode_node(data):
            b_size = 16
            if not data:
                return None
            node = {
                'keys': [],
                'datas': [],
                'subnode_addresses': [],
            }
            pos = 0
            number_of_keys, = struct.unpack_from('>I', data, pos)
            pos += 4
            keys = []
            for _ in range(number_of_keys):
                key_size, = struct.unpack_from('>I', data, pos)
                if not key_size or key_size > 32:
                    raise ValueError("fatal: !key_size || key_size > 32")
                pos += 4
                key = data[pos:pos + key_size]
                keys.append(key)
                pos += key_size
            number_of_datas, = struct.unpack_from('>I', data, pos)
            pos += 4
            datas = []
            for _ in range(number_of_datas):
                offset, = struct.unpack_from('>Q', data, pos)
                pos += 8
                length, = struct.unpack_from('>I', data, pos)
                pos += 4
                datas.append((offset, length))
            number_of_subnode_addresses = b_size + 1
            subnode_addresses = []
            for _ in range(number_of_subnode_addresses):
                subnode_address, = struct.unpack_from('>Q', data, pos)
                pos += 8
                subnode_addresses.append(subnode_address)
            node['keys'] = keys
            node['datas'] = datas
            node['subnode_addresses'] = subnode_addresses
            return node

        if not self.index_versions['init']:
            raise ValueError('index_versions_init failed!')
        url = f'http://{domain}/{index_dir}/{field}.{self.index_versions[index_dir]}.index'
        if field == 'galleries':
            url = f'http://{domain}/{galleries_index_dir}/galleries.{self.index_versions[galleries_index_dir]}.index'
        elif field == 'languages':
            url = f'http://{domain}/{languages_index_dir}/languages.{self.index_versions[languages_index_dir]}.index'
        elif field == 'nozomiurl':
            url = f'http://{domain}/{nozomiurl_index_dir}/nozomiurl.{self.index_versions[nozomiurl_index_dir]}.index'
        nodedata = Hitomi.get_url_at_range(url, [address, address + max_node_size - 1])
        return decode_node(nodedata)

    def b_search(self, field, key, node):
        print('b树搜索')

        def compare_arraybuffers(dv1, dv2):
            top = min(len(dv1), len(dv2))
            for i in range(top):
                if dv1[i] < dv2[i]:
                    return -1
                elif dv1[i] > dv2[i]:
                    return 1
            return 0

        def locate_key(inner_key, inner_node):
            cmp_result = -1
            i = 0
            for i, node_key in enumerate(inner_node['keys']):
                cmp_result = compare_arraybuffers(inner_key, node_key)
                if cmp_result <= 0:
                    break
            return [cmp_result == 0, i]

        def is_leaf(inner_node):
            return all(addr == 0 for addr in inner_node['subnode_addresses'])

        if not node:
            raise NotImplementedError('index_versions已过期')
        if not node['keys']:  # special case for empty root
            raise NotImplementedError('index_versions已过期')
        there, where = locate_key(key, node)
        if there:
            return node['datas'][where]
        elif is_leaf(node):
            raise NotImplementedError('index_versions已过期')
        if node['subnode_addresses'][where] == 0:
            raise NotImplementedError('index_versions已过期')
        subnode_address = node['subnode_addresses'][where]
        subnode = self.get_node_at_address(field, subnode_address)
        return self.b_search(field, key, subnode)

    def get_galleryids_for_query(self, inner_query, inner_state):
        def get_galleryids_from_data(inner_data):
            if not inner_data:
                return []
            url = f'http://{domain}/{galleries_index_dir}/galleries.{self.index_versions[galleries_index_dir]}.data'
            offset, length = inner_data
            if length > 100000000 or length <= 0:
                print(f"length {length} is too long")
                return []
            inbuf = Hitomi.get_url_at_range(url, [offset, offset + length - 1])
            if not inbuf:
                return []
            galleryids = []
            pos = 0
            number_of_galleryids = struct.unpack_from('>I', inbuf, pos)[0]  # big-endian int32
            pos += 4
            expected_length = number_of_galleryids * 4 + 4
            if number_of_galleryids > 10000000 or number_of_galleryids <= 0:
                print(f"number_of_galleryids {number_of_galleryids} is too long")
                return []
            elif len(inbuf) != expected_length:
                print(f"inbuf.byteLength {len(inbuf)} !== expected_length {expected_length}")
                return []
            for _ in range(number_of_galleryids):
                galleryid = struct.unpack_from('>I', inbuf, pos)[0]  # big-endian int32
                galleryids.append(galleryid)
                pos += 4
            return galleryids

        inner_query = inner_query.replace('_', ' ')

        def get_galleryids_from_nozomi(nozomi_state):
            if nozomi_state['orderby'] != 'date' or nozomi_state['orderbykey'] == 'published':
                if nozomi_state['area'] == 'all':
                    url = f"//{domain}/{nozomi_state['orderby']}/{nozomi_state['orderbykey']}-{nozomi_state['language']}{nozomiextension}"
                else:
                    url = f"//{domain}/{nozomi_state['area']}/{nozomi_state['orderby']}/{nozomi_state['orderbykey']}/{nozomi_state['tag']}-{nozomi_state['language']}{nozomiextension}"
            elif nozomi_state['area'] == 'all':
                url = f"//{domain}/{nozomi_state['tag']}-{nozomi_state['language']}{nozomiextension}"
            else:
                url = f"//{domain}/{nozomi_state['area']}/{nozomi_state['tag']}-{nozomi_state['language']}{nozomiextension}"
            response = requests.get(f'http:{url}')
            nozomi: list[int] = []
            if response.status_code == 200:
                array_buffer = response.content
                total = len(array_buffer) // 4
                for i in range(total):
                    nozomi.append(struct.unpack('>I', array_buffer[i * 4:(i + 1) * 4])[0])
            return nozomi

        initial_result = get_galleryids_from_nozomi(inner_state)
        print(f'初始搜索结果数{len(initial_result)}')
        key = hashlib.sha256(inner_query.encode()).digest()[:4]
        field = 'galleries'
        node = self.get_node_at_address(field, 0)
        if not node:
            print('not node')
            return []
        try:
            data = self.b_search(field, key, node)
        except NotImplementedError:
            self.refresh_version()
            try:
                data = self.b_search(field, key, node)
            except NotImplementedError:
                raise ValueError('B树搜索出错')
        if not data:
            print('not data')
            return []
        positive_result = get_galleryids_from_data(data)
        print(f'正向搜索结果数{len(positive_result)}')
        filted_result = [gallery for gallery in initial_result if gallery in positive_result]
        return filted_result

    def process_query(self, query_string):
        terms = urllib.parse.unquote(query_string).lower().strip().split()
        inner_state = {
            'area': 'all',
            'tag': 'index',
            'language': 'chinese',
            'orderby': 'date',
            'orderbykey': 'added',
            'orderbydirection': 'desc'
        }
        return self.get_galleryids_for_query(terms[0], inner_state)

    def download(self, gellary_id):
        download_path = self.storage_path
        downloaded_files_path = []
        if not os.path.exists('temp'):
            os.makedirs('temp')
        gallery_info = self.get_gallery_info(gellary_id)
        urls = self.get_download_urls(gallery_info)
        headers = {
            'referer': 'https://hitomi.la' + urllib.parse.quote(gallery_info['galleryurl'])
        }

        def download_file(url):
            for name, url in urls.items():
                with open(f"temp/{name}", 'wb') as f:
                    print(f'downloading {name}')
                    repsone = requests.get(url, headers=headers)
                    if repsone.status_code != 200:
                        if repsone.status_code == 404 or repsone.status_code == 403:
                            raise NotImplementedError('反爬虫配置可能已失效')
                    f.write(repsone.content)
                    downloaded_files_path.append(f"temp/{name}")

        try:
            download_file(urls)
            print('下载完成')
        except NotImplementedError:
            print('反爬配置失效，正在重新配置')
            downloaded_files_path = []
            self.set_gg()
            try:
                download_file(urls)
            except NotImplementedError:
                raise ValueError('爬虫失效')

        def clean_filename(filename):
            # 定义不允许的字符
            illegal_chars = {'\\', '/', ':', '*', '?', '"', '<', '>', '|'}
            # 替换不允许的字符为空格
            cleaned_filename = ''.join(c if c not in illegal_chars else ' ' for c in filename)
            # 去除连续空格并去除首尾空格
            cleaned_filename = ' '.join(cleaned_filename.split())
            return cleaned_filename

        with zipfile.ZipFile(os.path.join(download_path, 'temp.zip'), 'w') as zipf:
            for file_path in downloaded_files_path:
                zipf.write(file_path, arcname=os.path.basename(file_path))
        for img in os.listdir('temp'):
            img_path = os.path.join('temp', img)
            os.remove(img_path)
        os.rename(os.path.join(download_path, 'temp.zip'), os.path.join(download_path, clean_filename(gallery_info['title']) + '.zip'))
        print('压缩完成')


dler = Hitomi()
dler.download(2859991)
