import socket
import struct
import time
import os

# === CONFIGURATION ===
# Replace with the exact fe80:: string you successfully pinged
PI_IPV6 = "fe80::ccff:e39d:dc2:99c7" 
# Use the interface name that worked (e.g., 'eth1' or 'eth0')
INTERFACE = "eth1" 
# =====================

def checksum(source_string):
    sum = 0
    countTo = (len(source_string) // 2) * 2
    count = 0
    while count < countTo:
        thisVal = source_string[count + 1] * 256 + source_string[count]
        sum = sum + thisVal
        sum = sum & 0xffffffff
        count = count + 2

    if countTo < len(source_string):
        sum = sum + source_string[len(source_string) - 1]
        sum = sum & 0xffffffff

    sum = (sum >> 16) + (sum & 0xffff)
    sum = sum + (sum >> 16)
    answer = ~sum
    answer = answer & 0xffff
    answer = answer >> 8 | (answer << 8 & 0xff00)
    return answer

def ping_pi():
    # ICMPv6 protocol number is 58
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_RAW, 58)
    except PermissionError:
        print("Error: This script requires root privileges. Run with 'sudo'.")
        return

    # Bind to the specific WSL interface channel
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, INTERFACE.encode())
    
    # Packet header details: Type=128 (Echo Request), Code=0, Checksum=0, ID=1, Sequence=1
    my_checksum = 0
    pid = os.getpid() & 0xFFFF
    header = struct.pack("!BBHHH", 128, 0, my_checksum, pid, 1)
    data = struct.pack("!d", time.time()) # Timestamp as payload
    
    # Calculate actual checksum
    my_checksum = checksum(header + data)
    header = struct.pack("!BBHHH", 128, 0, my_checksum, pid, 1)
    packet = header + data

    # Scope ID payload tuple for IPv6: (target, port, flowinfo, scope_id)
    # Fetching the interface index automatically for the scope
    scope_id = socket.if_nametoindex(INTERFACE)
    target_address = (PI_IPV6, 0, 0, scope_id)

    print(f"Sending Python ICMPv6 ping to {PI_IPV6} via {INTERFACE}...")
    
    try:
        sock.sendto(packet, target_address)
        start_time = time.time()
        
        # Set a 2-second timeout for the response
        sock.settimeout(2.0)
        
        # Wait for reply
        reply_packet, addr = sock.recvfrom(1024)
        end_time = time.time()
        
        elapsed = (end_time - start_time) * 1000
        print(f"Success! Reply received from {addr[0]}")
        print(f"Connection strength: Stable | Latency: {elapsed:.2f} ms")
        
    except socket.timeout:
        print("Ping timed out. The network path is up, but the Pi didn't reply.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        sock.close()

if __name__ == "__main__":
    ping_pi()