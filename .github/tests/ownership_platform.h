#import <Cocoa/Cocoa.h>
#import <dispatch/dispatch.h>

@interface OwnershipWindow : NSObject
- (NSString *)tabbingIdentifier;
- (void)setTabbingIdentifier:(NSString *)value;
- (void)setTabbingMode:(NSWindowTabbingMode)mode;
- (void)toggleTabOverview:(id)sender;
- (void)toggleTabBar:(id)sender;
- (void)mergeAllWindows:(id)sender;
- (void)selectNextTab:(id)sender;
- (void)selectPreviousTab:(id)sender;
@end
@interface OwnershipThread : NSObject
+ (BOOL)isMainThread;
@end
dispatch_queue_t OwnershipQueue(void);
void OwnershipSync(dispatch_queue_t, dispatch_block_t);
void OwnershipAsync(dispatch_queue_t, dispatch_block_t);
void OwnershipScale(CGContextRef, CGFloat, CGFloat);
void OwnershipTranslate(CGContextRef, CGFloat, CGFloat);
#define NSWindow OwnershipWindow
#define NSThread OwnershipThread
#define dispatch_get_main_queue OwnershipQueue
#define dispatch_sync OwnershipSync
#define dispatch_async OwnershipAsync
#define CGContextScaleCTM OwnershipScale
#define CGContextTranslateCTM OwnershipTranslate
