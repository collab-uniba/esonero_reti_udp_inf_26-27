/*
 * main.c
 *
 * UDP Client - Template for Computer Networks assignment
 *
 * This file contains the boilerplate code for a UDP client
 * portable across Windows, Linux and macOS.
 */

#if defined WIN32
#include <winsock.h>
typedef int socklen_t;
#else
#include <unistd.h>
#include <sys/types.h>
#include <sys/time.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netdb.h>
#define closesocket close
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "protocol.h"

#define NO_ERROR 0

void clearwinsock() {
#if defined WIN32
	WSACleanup();
#endif
}

int main(int argc, char *argv[]) {

	// TODO: Implement client logic

#if defined WIN32
	// Initialize Winsock
	WSADATA wsa_data;
	int result = WSAStartup(MAKEWORD(2,2), &wsa_data);
	if (result != NO_ERROR) {
		printf("Error at WSAStartup()\n");
		return EXIT_FAILURE;
	}
#endif

	int my_socket;

	// TODO: Create socket
	// my_socket = socket(...);

	// TODO: Set the receive timeout (see Assegnazione.md)

	// TODO: Resolve the server name (-s) to an IP address
	// gethostbyname(...);

	// TODO: Configure server address
	// struct sockaddr_in server_addr;
	// ...

	// TODO: Implement communication logic (no connect(): see Assegnazione.md)
	// sendto(...);
	// recvfrom(...);   // then validate the response (see Assegnazione.md)

	// TODO: Close socket
	// closesocket(my_socket);

	clearwinsock();
	return EXIT_SUCCESS;
} // main end
