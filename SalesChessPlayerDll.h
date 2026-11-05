#ifndef SALES_CHESS_PLAYER_DLL_H
#define SALES_CHESS_PLAYER_DLL_H

#include <wchar.h>

#if defined(SALES_CHESS_PLAYER_DLL_BUILD)
#define SALES_CHESS_PLAYER_API __declspec(dllexport)
#else
#define SALES_CHESS_PLAYER_API __declspec(dllimport)
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Starts the sibling SalesChessPlayer.exe. Returns 1 if started, 0 if already
   running, and -1 if the executable could not be launched. */
SALES_CHESS_PLAYER_API int __cdecl SalesChessPlayer_Start(void);

/* Requests a normal window close. Returns 1 if stopped, 0 if it was not
   running, and -1 if it did not close before timeout_ms elapsed. */
SALES_CHESS_PLAYER_API int __cdecl SalesChessPlayer_Stop(unsigned long timeout_ms);

/* Returns 1 while the app is running, otherwise 0. */
SALES_CHESS_PLAYER_API int __cdecl SalesChessPlayer_IsRunning(void);

/* Returns the last Win32 error code set by a DLL call; zero means no error. */
SALES_CHESS_PLAYER_API unsigned long __cdecl SalesChessPlayer_GetLastErrorCode(void);

#ifdef __cplusplus
}
#endif

#endif
