/*
 * main.c
 *
 * UDP Server - Template for Computer Networks assignment
 *
 * This file contains the boilerplate code for a UDP server
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

	// Disable stdout buffering so that log lines are printed immediately
	setvbuf(stdout, NULL, _IONBF, 0);

	// TODO: Implement server logic

#if defined WIN32
	// Initialize Winsock
	WSADATA wsa_data;
	int result = WSAStartup(MAKEWORD(2,2), &wsa_data);
	if (result != NO_ERROR) {
		printf("Error at WSAStartup()\n");
		return EXIT_FAILURE;
	}
#endif

	int my_socket = -1;

	// TODO: Create socket
	// my_socket = socket(...);

	// TODO: Configure server address
	// struct sockaddr_in server_addr;
	// server_addr.sin_family = AF_INET;
	// server_addr.sin_port = htons(port);  // SERVER_PORT, or the value of -p
	// server_addr.sin_addr.s_addr = htonl(INADDR_ANY);  // 0.0.0.0: receive datagrams on any interface (127.0.0.1 included)

	// TODO: Bind socket
	// bind(...);

	// TODO: Implement the request loop
	// while (1) {
	//     recvfrom(...);   // receive a request and the client address
	//     // Ignore invalid datagrams and recvfrom() errors: never terminate
	//     // Handle the request
	//     sendto(...);     // reply to the client address
	// }

	closesocket(my_socket);
	clearwinsock();
	return EXIT_SUCCESS;
} // main end
