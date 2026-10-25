import threading
import os
import json
import socket
import struct
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.clock import Clock

BASE_BRANCHES = 256
BLOCK_SIZE = 32
GROUP_SIZE = 10

class KinshipReceiverApp(App):
    def build(self):
        self.layout = BoxLayout(orientation='vertical', padding=20, spacing=20)
        
        self.status_label = Label(
            text="[*] مستقبل الأنساب جاهز للعمل عبر البلوتوث...",
            font_size=18,
            halign='center'
        )
        self.layout.add_widget(self.status_label)
        
        self.btn = Button(
            text="بدء الاستماع للبلوتوث",
            size_hint=(1, 0.3),
            background_color=(0.1, 0.6, 0.3, 1)
        )
        self.btn.bind(on_press=self.start_listener_thread)
        self.layout.add_widget(self.btn)
        
        return self.layout

    def start_listener_thread(self, instance):
        self.btn.disabled = True
        self.status_label.text = "[* جاري الاستماع على قناة RFCOMM 1...]"
        threading.Thread(target=self.run_bluetooth_receiver, daemon=True).start()

    def run_bluetooth_receiver(self):
        port = 1
        try:
            server_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            server_sock.bind(("", port))
            server_sock.listen(1)
        except Exception as e:
            Clock.schedule_once(lambda dt: setattr(self.status_label, 'text', f"[خطأ سوكت]: {e}"))
            return
        
        while True:
            try:
                client_sock, client_info = server_sock.accept()
                Clock.schedule_once(lambda dt: setattr(self.status_label, 'text', f"[*] متصل مع: {client_info}"))
                
                received_clades = {}
                parity_store = {}
                
                while True:
                    # قراءة الهيدر (Length Header)
                    length_header = client_sock.recv(4)
                    if not length_header or len(length_header) < 4:
                        break
                    packet_len = struct.unpack('!I', length_header)[0]
                    
                    data_chunks = []
                    bytes_received = 0
                    while bytes_received < packet_len:
                        chunk = client_sock.recv(min(packet_len - bytes_received, 4096))
                        if not chunk:
                            break
                        data_chunks.append(chunk)
                        bytes_received += len(chunk)
                        
                    packet = json.loads(b''.join(data_chunks).decode('utf-8'))
                    
                    if packet['type'] == 'clade':
                        c_id = packet['clade_id']
                        lineage = packet['lineage']
                        chunk_len = packet['chunk_len']
                        
                        healed_lineage = []
                        last_valid_node = 0
                        is_corrupted = False
                        
                        for i in range(len(lineage)):
                            node, sig = lineage[i]
                            expected_sig = (node * 7 + i) % 1000
                            if sig != expected_sig:
                                is_corrupted = True
                                reconstructed_node = (last_valid_node * BASE_BRANCHES) + 1
                                reconstructed_sig = (reconstructed_node * 7 + i) % 1000
                                healed_lineage.append((reconstructed_node, reconstructed_sig))
                                last_valid_node = reconstructed_node
                            else:
                                healed_lineage.append((node, sig))
                                last_valid_node = node
                                
                        received_clades[c_id] = {
                            'lineage': healed_lineage,
                            'chunk_len': chunk_len,
                            'corrupted': is_corrupted
                        }
                        
                    elif packet['type'] == 'parity':
                        parity_store[packet['group_id']] = {
                            'members': packet['members'],
                            'parity_bytes': bytearray(packet['parity_bytes'])
                        }
                
                client_sock.close()
                
                # تطبيق التصحيح الرياضي عبر الحراسة وحفظ الملف
                max_id = max(received_clades.keys())
                total_expected = max_id + 1
                
                for group_id, p_info in parity_store.items():
                    members = p_info['members']
                    p_bytes = p_info['parity_bytes']
                    corrupted_in_group = [cid for cid in members if cid in received_clades and received_clades[cid]['corrupted']]
                    missing_in_group = [cid for cid in members if cid not in received_clades]
                    target_fix = corrupted_in_group + missing_in_group
                    
                    if len(target_fix) == 1:
                        bad_cid = target_fix[0]
                        recovered_chunk_bytes = bytearray(p_bytes)
                        for cid in members:
                            if cid == bad_cid: continue
                            if cid in received_clades and not received_clades[cid]['corrupted']:
                                clade = received_clades[cid]
                                dec_val = sum(((n - 1) % BASE_BRANCHES) * (BASE_BRANCHES**idx) for idx, (n, s) in enumerate(clade['lineage']))
                                try: c_bytes = dec_val.to_bytes(clade['chunk_len'], 'big')
                                except: c_bytes = dec_val.to_bytes(max(1, (dec_val.bit_length()+7)//8), 'big')
                                padded_c = c_bytes + b'\x00' * (BLOCK_SIZE - len(c_bytes))
                                for b_i in range(BLOCK_SIZE): recovered_chunk_bytes[b_i] ^= padded_c[b_i]
                        
                        chunk_len = received_clades[bad_cid]['chunk_len'] if bad_cid in received_clades else BLOCK_SIZE
                        actual_bytes = recovered_chunk_bytes[:chunk_len]
                        dec_val = int.from_bytes(actual_bytes, 'big')
                        
                        new_lineage = []
                        last_node, step = 0, 0
                        tv = dec_val
                        while tv > 0:
                            branch = tv % BASE_BRANCHES
                            candidate = (last_node * BASE_BRANCHES) + branch + 1
                            new_lineage.append((candidate, (candidate * 7 + step) % 1000))
                            last_node = candidate
                            step += 1
                            tv //= BASE_BRANCHES
                        if not new_lineage: new_lineage.append((0, 0))
                        
                        received_clades[bad_cid] = {'lineage': new_lineage, 'chunk_len': chunk_len, 'corrupted': False}
                
                recovered_bytes = bytearray()
                for i in range(total_expected):
                    if i in received_clades:
                        clade = received_clades[i]
                        dec_val = sum(((n - 1) % BASE_BRANCHES) * (BASE_BRANCHES**idx) for idx, (n, s) in enumerate(clade['lineage']))
                        try: c_bytes = dec_val.to_bytes(clade['chunk_len'], 'big')
                        except:
                            bl = max(1, (dec_val.bit_length() + 7) // 8)
                            c_bytes = dec_val.to_bytes(bl, 'big')
                            c_bytes = (b'\x00' * (clade['chunk_len'] - len(c_bytes)) + c_bytes) if len(c_bytes) < clade['chunk_len'] else c_bytes[-clade['chunk_len']:]
                        recovered_bytes.extend(c_bytes)
                    else:
                        recovered_bytes.extend(b'\x00' * BLOCK_SIZE)
                
                # حفظ الملف في مجلد التخزين الخارجي أو المستندات
                save_path = os.path.join(App.get_running_app().user_data_dir, "bt_received.txt")
                with open(save_path, 'wb') as f:
                    f.write(recovered_bytes)
                
                Clock.schedule_once(lambda dt: setattr(self.status_label, 'text', f"[نجاح مطلق!] تم الحفظ في:\n{save_path}"))
                break
                
            except Exception as e:
                Clock.schedule_once(lambda dt: setattr(self.status_label, 'text', f"[خطأ]: {e}"))
                break

if __name__ == '__main__':
    KinshipReceiverApp().run()
